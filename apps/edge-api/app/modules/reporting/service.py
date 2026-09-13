from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    ReviewStatus,
)
from app.core.errors import DomainError, ForbiddenError
from app.core.principals import Principal
from app.modules.catalog.models import Product, ProductTranslation
from app.modules.kitchen_fulfillment.models import FulfillmentTicket
from app.modules.manual_review.models import ManualReviewCase
from app.modules.ordering.models import OrderItem, SalesOrder
from app.modules.organization.models import LegalEntity, Store
from app.modules.organization.service import get_store_for_tenant
from app.modules.payments.models import (
    PaymentAttempt,
    ReconciliationIssue,
    ReconciliationRun,
    Refund,
)
from app.modules.reporting.schemas import (
    DashboardKpiResponse,
    DashboardKpiStore,
    FulfillmentSummaryResponse,
    MultiStoreSummaryResponse,
    ReconciliationSummaryResponse,
    RefundSummaryResponse,
    SalesSummaryResponse,
    StoreSalesSnapshot,
    TopProductItem,
    TopProductsResponse,
    TrendBucket,
)

_AMSTERDAM = ZoneInfo("Europe/Amsterdam")


def _business_timezone() -> ZoneInfo:
    return _AMSTERDAM


def _local_date(instant: datetime) -> date:
    """Convert a UTC-aware instant to the tenant business date (Europe/Amsterdam)."""
    if instant.tzinfo is None or instant.utcoffset() is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(_AMSTERDAM).date()


def _bucket_period(day: date, period: str) -> str:
    if period == "day":
        return day.isoformat()
    if period == "month":
        return f"{day.year:04d}-{day.month:02d}"
    iso = day.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def report_period_window(period: str) -> tuple[datetime, datetime]:
    """Resolve a named report period into a half-open UTC window [start_at, end_at)."""
    tz = _business_timezone()
    today = datetime.now(tz).date()

    def midnight(day: date) -> datetime:
        return datetime.combine(day, time.min, tzinfo=tz)

    if period == "this_week":
        start_day = today - timedelta(days=today.weekday())
        start = midnight(start_day)
        end = start + timedelta(days=7)
    elif period == "last_week":
        start = midnight(today - timedelta(days=today.weekday() + 7))
        end = start + timedelta(days=7)
    elif period == "this_month":
        start = midnight(today.replace(day=1))
        if today.month == 12:
            next_month = datetime(today.year + 1, 1, 1).date()
        else:
            next_month = datetime(today.year, today.month + 1, 1).date()
        end = midnight(next_month)
    elif period == "last_month":
        if today.month == 1:
            start = midnight(datetime(today.year - 1, 12, 1).date())
            end = midnight(datetime(today.year, 1, 1).date())
        else:
            start = midnight(datetime(today.year, today.month - 1, 1).date())
            end = midnight(datetime(today.year, today.month, 1).date())
    else:
        raise DomainError("invalid_report_period", f"Unknown report period: {period}")
    return start.astimezone(UTC), end.astimezone(UTC)


async def _resolve_report_stores(
    session: AsyncSession,
    principal: Principal,
    requested: list[UUID] | None,
) -> list[Store]:
    if requested:
        requested_set = set(requested)
        if not requested_set.issubset(set(principal.store_ids)):
            raise ForbiddenError(
                "The user is not authorized for one or more of the requested stores"
            )
        store_ids = sorted(requested_set, key=str)
    else:
        store_ids = sorted(principal.store_ids, key=str)
    if not store_ids:
        return []
    stores = list(
        (
            await session.scalars(
                select(Store)
                .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
                .where(
                    Store.id.in_(store_ids),
                    Store.active,
                    LegalEntity.active,
                    LegalEntity.tenant_id == principal.tenant_id,
                )
                .order_by(Store.code)
            )
        ).all()
    )
    return stores


def _report_window(start_at: datetime, end_at: datetime) -> tuple[datetime, datetime]:
    if start_at.tzinfo is None or start_at.utcoffset() is None:
        raise DomainError("invalid_report_window", "start_at must include a UTC offset")
    if end_at.tzinfo is None or end_at.utcoffset() is None:
        raise DomainError("invalid_report_window", "end_at must include a UTC offset")
    normalized_start = start_at.astimezone(UTC)
    normalized_end = end_at.astimezone(UTC)
    if normalized_end <= normalized_start:
        raise DomainError("invalid_report_window", "end_at must be later than start_at")
    return normalized_start, normalized_end


def _integer_average(values: list[float]) -> int | None:
    if not values:
        return None
    return round(sum(values) / len(values))


async def get_sales_summary(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    start_at: datetime,
    end_at: datetime,
) -> SalesSummaryResponse:
    start_at, end_at = _report_window(start_at, end_at)
    store = await get_store_for_tenant(session, principal, store_id)
    row = (
        await session.execute(
            select(
                func.count(SalesOrder.id),
                func.coalesce(func.sum(SalesOrder.total_minor), 0),
                func.coalesce(func.sum(SalesOrder.discount_minor), 0),
                func.coalesce(func.sum(SalesOrder.net_minor), 0),
                func.coalesce(func.sum(SalesOrder.tax_minor), 0),
                func.coalesce(func.sum(SalesOrder.paid_minor), 0),
                func.coalesce(func.sum(SalesOrder.refunded_minor), 0),
            ).where(
                SalesOrder.store_id == store.id,
                SalesOrder.tenant_id == principal.tenant_id,
                SalesOrder.status.in_((OrderStatus.CONFIRMED, OrderStatus.CLOSED)),
                SalesOrder.confirmed_at >= start_at,
                SalesOrder.confirmed_at < end_at,
            )
        )
    ).one()
    order_count, gross, discount, net, tax, paid, refunded = (int(value or 0) for value in row)
    return SalesSummaryResponse(
        store_id=store.id,
        start_at=start_at,
        end_at=end_at,
        currency=store.currency,
        order_count=order_count,
        gross_sales_minor=gross,
        discount_minor=discount,
        net_minor=net,
        tax_minor=tax,
        paid_minor=paid,
        refunded_minor=refunded,
        net_collected_minor=paid - refunded,
    )


async def get_refund_summary(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    start_at: datetime,
    end_at: datetime,
) -> RefundSummaryResponse:
    start_at, end_at = _report_window(start_at, end_at)
    store = await get_store_for_tenant(session, principal, store_id)
    rows = (
        await session.execute(
            select(
                Refund.status,
                func.count(Refund.id),
                func.coalesce(func.sum(Refund.amount_minor), 0),
            )
            .join(SalesOrder, SalesOrder.id == Refund.order_id)
            .where(
                SalesOrder.store_id == store.id,
                SalesOrder.tenant_id == principal.tenant_id,
                Refund.created_at >= start_at,
                Refund.created_at < end_at,
            )
            .group_by(Refund.status)
        )
    ).all()
    status_counts = {status: 0 for status in RefundStatus}
    status_amounts = {status: 0 for status in RefundStatus}
    for status, count, amount in rows:
        status_counts[status] = int(count)
        status_amounts[status] = int(amount)
    return RefundSummaryResponse(
        store_id=store.id,
        start_at=start_at,
        end_at=end_at,
        currency=store.currency,
        refund_count=sum(status_counts.values()),
        requested_minor=sum(status_amounts.values()),
        succeeded_minor=status_amounts[RefundStatus.SUCCEEDED],
        status_counts=status_counts,
        status_amounts_minor=status_amounts,
    )


async def get_fulfillment_summary(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    start_at: datetime,
    end_at: datetime,
) -> FulfillmentSummaryResponse:
    start_at, end_at = _report_window(start_at, end_at)
    store = await get_store_for_tenant(session, principal, store_id)
    tickets = list(
        (
            await session.scalars(
                select(FulfillmentTicket)
                .join(SalesOrder, SalesOrder.id == FulfillmentTicket.order_id)
                .where(
                    SalesOrder.store_id == store.id,
                    SalesOrder.tenant_id == principal.tenant_id,
                    FulfillmentTicket.created_at >= start_at,
                    FulfillmentTicket.created_at < end_at,
                )
            )
        ).all()
    )
    status_counts = {status: 0 for status in FulfillmentStatus}
    acknowledgement_seconds: list[float] = []
    ready_seconds: list[float] = []
    collection_seconds: list[float] = []
    for ticket in tickets:
        status_counts[ticket.status] += 1
        if ticket.acknowledged_at is not None:
            acknowledgement_seconds.append(
                (ticket.acknowledged_at - ticket.created_at).total_seconds()
            )
        if ticket.ready_at is not None:
            ready_seconds.append((ticket.ready_at - ticket.created_at).total_seconds())
        if ticket.ready_at is not None and ticket.collected_at is not None:
            collection_seconds.append((ticket.collected_at - ticket.ready_at).total_seconds())
    return FulfillmentSummaryResponse(
        store_id=store.id,
        start_at=start_at,
        end_at=end_at,
        ticket_count=len(tickets),
        status_counts=status_counts,
        average_seconds_to_acknowledge=_integer_average(acknowledgement_seconds),
        average_seconds_to_ready=_integer_average(ready_seconds),
        average_seconds_ready_to_collect=_integer_average(collection_seconds),
    )


async def get_reconciliation_summary(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    start_at: datetime,
    end_at: datetime,
) -> ReconciliationSummaryResponse:
    start_at, end_at = _report_window(start_at, end_at)
    store = await get_store_for_tenant(session, principal, store_id)
    runs = list(
        (
            await session.scalars(
                select(ReconciliationRun)
                .where(
                    ReconciliationRun.store_id == store.id,
                    ReconciliationRun.started_at >= start_at,
                    ReconciliationRun.started_at < end_at,
                )
                .order_by(ReconciliationRun.started_at.desc())
            )
        ).all()
    )
    issues = list(
        (
            await session.scalars(
                select(ReconciliationIssue)
                .join(ReconciliationRun, ReconciliationRun.id == ReconciliationIssue.run_id)
                .where(
                    ReconciliationRun.store_id == store.id,
                    ReconciliationRun.started_at >= start_at,
                    ReconciliationRun.started_at < end_at,
                    ReconciliationIssue.resolved_at.is_(None),
                )
            )
        ).all()
    )
    latest = runs[0] if runs else None
    return ReconciliationSummaryResponse(
        store_id=store.id,
        start_at=start_at,
        end_at=end_at,
        run_count=len(runs),
        completed_run_count=sum(run.status.upper() == "COMPLETED" for run in runs),
        failed_run_count=sum(run.status.upper() == "FAILED" for run in runs),
        open_issue_count=len(issues),
        critical_open_issue_count=sum(issue.severity.upper() == "CRITICAL" for issue in issues),
        latest_run_status=latest.status if latest is not None else None,
        latest_run_started_at=latest.started_at if latest is not None else None,
        latest_run_completed_at=latest.completed_at if latest is not None else None,
    )


async def get_top_products(
    session: AsyncSession,
    principal: Principal,
    *,
    store_ids: list[UUID] | None,
    start_at: datetime,
    end_at: datetime,
    order_by: str,
    limit: int,
    locale: str,
) -> TopProductsResponse:
    start_at, end_at = _report_window(start_at, end_at)
    stores = await _resolve_report_stores(session, principal, store_ids)
    resolved_store_ids = [store.id for store in stores]
    currency = stores[0].currency if stores else "EUR"
    if not resolved_store_ids:
        return TopProductsResponse(
            store_ids=resolved_store_ids,
            start_at=start_at,
            end_at=end_at,
            order_by=order_by,
            limit=limit,
            currency=currency,
            items=[],
        )
    revenue_column = func.sum(OrderItem.line_total_minor)
    quantity_column = func.sum(OrderItem.quantity)
    order_column = quantity_column if order_by == "quantity" else revenue_column
    rows = (
        await session.execute(
            select(
                OrderItem.product_id,
                quantity_column,
                revenue_column,
            )
            .join(SalesOrder, SalesOrder.id == OrderItem.order_id)
            .where(
                SalesOrder.store_id.in_(resolved_store_ids),
                SalesOrder.tenant_id == principal.tenant_id,
                SalesOrder.status.in_((OrderStatus.CONFIRMED, OrderStatus.CLOSED)),
                SalesOrder.confirmed_at >= start_at,
                SalesOrder.confirmed_at < end_at,
            )
            .group_by(OrderItem.product_id)
            .order_by(order_column.desc(), quantity_column.desc())
            .limit(limit)
        )
    ).all()
    product_ids = [product_id for product_id, _, _ in rows]
    products: dict[UUID, Product] = {}
    if product_ids:
        for product in (
            await session.scalars(
                select(Product).where(
                    Product.id.in_(product_ids),
                    Product.tenant_id == principal.tenant_id,
                )
            )
        ).all():
            products[product.id] = product
    names: dict[UUID, str] = {}
    if product_ids:
        locales = [locale, "nl-NL", "en"]
        translations: dict[tuple[UUID, str], str] = {}
        for translation in (
            await session.scalars(
                select(ProductTranslation).where(
                    ProductTranslation.product_id.in_(product_ids),
                    ProductTranslation.locale.in_(locales),
                )
            )
        ).all():
            translations.setdefault((translation.product_id, translation.locale), translation.name)
        for product_id in product_ids:
            for candidate in locales:
                value = translations.get((product_id, candidate))
                if value:
                    names[product_id] = value
                    break
    items: list[TopProductItem] = []
    for product_id, quantity, revenue in rows:
        product = products.get(product_id)
        items.append(
            TopProductItem(
                product_id=product_id,
                sku=product.sku if product else str(product_id),
                name=names.get(product_id, product.sku if product else str(product_id)),
                quantity=int(quantity or 0),
                revenue_minor=int(revenue or 0),
                currency=currency,
            )
        )
    return TopProductsResponse(
        store_ids=resolved_store_ids,
        start_at=start_at,
        end_at=end_at,
        order_by=order_by,
        limit=limit,
        currency=currency,
        items=items,
    )


async def get_multi_store_summary(
    session: AsyncSession,
    principal: Principal,
    *,
    store_ids: list[UUID] | None,
    start_at: datetime,
    end_at: datetime,
    period: str,
) -> MultiStoreSummaryResponse:
    start_at, end_at = _report_window(start_at, end_at)
    stores = await _resolve_report_stores(session, principal, store_ids)
    resolved_store_ids = [store.id for store in stores]
    currency = stores[0].currency if stores else "EUR"

    totals = StoreSalesSnapshot(
        order_count=0,
        gross_sales_minor=0,
        discount_minor=0,
        net_sales_minor=0,
        tax_minor=0,
        refunded_minor=0,
        net_collected_minor=0,
        ticket_count=0,
    )
    store_snapshots: dict[UUID, StoreSalesSnapshot] = {}

    if resolved_store_ids:
        sales_rows = (
            await session.execute(
                select(
                    SalesOrder.store_id,
                    func.count(SalesOrder.id),
                    func.coalesce(func.sum(SalesOrder.total_minor), 0),
                    func.coalesce(func.sum(SalesOrder.discount_minor), 0),
                    func.coalesce(func.sum(SalesOrder.net_minor), 0),
                    func.coalesce(func.sum(SalesOrder.tax_minor), 0),
                    func.coalesce(func.sum(SalesOrder.paid_minor), 0),
                    func.coalesce(func.sum(SalesOrder.refunded_minor), 0),
                )
                .where(
                    SalesOrder.store_id.in_(resolved_store_ids),
                    SalesOrder.tenant_id == principal.tenant_id,
                    SalesOrder.status.in_((OrderStatus.CONFIRMED, OrderStatus.CLOSED)),
                    SalesOrder.confirmed_at >= start_at,
                    SalesOrder.confirmed_at < end_at,
                )
                .group_by(SalesOrder.store_id)
            )
        ).all()
        refund_rows = (
            await session.execute(
                select(
                    SalesOrder.store_id,
                    func.coalesce(func.sum(Refund.amount_minor), 0),
                )
                .join(SalesOrder, SalesOrder.id == Refund.order_id)
                .where(
                    SalesOrder.store_id.in_(resolved_store_ids),
                    SalesOrder.tenant_id == principal.tenant_id,
                    Refund.created_at >= start_at,
                    Refund.created_at < end_at,
                )
                .group_by(SalesOrder.store_id)
            )
        ).all()
        ticket_rows = (
            await session.execute(
                select(
                    SalesOrder.store_id,
                    func.count(FulfillmentTicket.id),
                )
                .join(SalesOrder, SalesOrder.id == FulfillmentTicket.order_id)
                .where(
                    SalesOrder.store_id.in_(resolved_store_ids),
                    SalesOrder.tenant_id == principal.tenant_id,
                    FulfillmentTicket.created_at >= start_at,
                    FulfillmentTicket.created_at < end_at,
                )
                .group_by(SalesOrder.store_id)
            )
        ).all()

        refunded_by_store = {store_id: int(amount) for store_id, amount in refund_rows}
        tickets_by_store = {store_id: int(count) for store_id, count in ticket_rows}
        for store_id, order_count, gross, discount, net, tax, paid, _refunded in sales_rows:
            refunded_amount = refunded_by_store.get(store_id, 0)
            store = next(s for s in stores if s.id == store_id)
            snapshot = StoreSalesSnapshot(
                store_id=store_id,
                store_code=store.code,
                store_name=store.name,
                order_count=int(order_count),
                gross_sales_minor=int(gross),
                discount_minor=int(discount),
                net_sales_minor=int(net),
                tax_minor=int(tax),
                refunded_minor=refunded_amount,
                net_collected_minor=int(paid) - refunded_amount,
                ticket_count=tickets_by_store.get(store_id, 0),
            )
            store_snapshots[store_id] = snapshot
            totals.order_count += snapshot.order_count
            totals.gross_sales_minor += snapshot.gross_sales_minor
            totals.discount_minor += snapshot.discount_minor
            totals.net_sales_minor += snapshot.net_sales_minor
            totals.tax_minor += snapshot.tax_minor
            totals.refunded_minor += snapshot.refunded_minor
            totals.net_collected_minor += snapshot.net_collected_minor
            totals.ticket_count += snapshot.ticket_count

    # Trend: group orders by business date, refunds and tickets by business date.
    order_trend: dict[date, dict[str, int]] = defaultdict(
        lambda: {"order_count": 0, "gross_sales_minor": 0, "refunded_minor": 0, "ticket_count": 0}
    )
    if resolved_store_ids:
        order_rows = (
            await session.execute(
                select(
                    SalesOrder.business_date,
                    func.count(SalesOrder.id),
                    func.coalesce(func.sum(SalesOrder.total_minor), 0),
                    func.coalesce(func.sum(SalesOrder.refunded_minor), 0),
                )
                .where(
                    SalesOrder.store_id.in_(resolved_store_ids),
                    SalesOrder.tenant_id == principal.tenant_id,
                    SalesOrder.status.in_((OrderStatus.CONFIRMED, OrderStatus.CLOSED)),
                    SalesOrder.confirmed_at >= start_at,
                    SalesOrder.confirmed_at < end_at,
                )
                .group_by(SalesOrder.business_date)
            )
        ).all()
        for business_date_value, order_count, gross, refunded in order_rows:
            entry = order_trend[business_date_value]
            entry["order_count"] += int(order_count)
            entry["gross_sales_minor"] += int(gross)
            entry["refunded_minor"] += int(refunded)

        refund_tickets = (
            await session.execute(
                select(Refund.created_at, Refund.amount_minor)
                .join(SalesOrder, SalesOrder.id == Refund.order_id)
                .where(
                    SalesOrder.store_id.in_(resolved_store_ids),
                    SalesOrder.tenant_id == principal.tenant_id,
                    Refund.created_at >= start_at,
                    Refund.created_at < end_at,
                )
            )
        ).all()
        for created_at, amount in refund_tickets:
            day = _local_date(created_at)
            order_trend[day]["refunded_minor"] += int(amount)

        ticket_stamps = (
            await session.execute(
                select(FulfillmentTicket.created_at)
                .join(SalesOrder, SalesOrder.id == FulfillmentTicket.order_id)
                .where(
                    SalesOrder.store_id.in_(resolved_store_ids),
                    SalesOrder.tenant_id == principal.tenant_id,
                    FulfillmentTicket.created_at >= start_at,
                    FulfillmentTicket.created_at < end_at,
                )
            )
        ).all()
        for (created_at,) in ticket_stamps:
            day = _local_date(created_at)
            order_trend[day]["ticket_count"] += 1

    bucket_trend: dict[str, dict[str, int]] = defaultdict(
        lambda: {"order_count": 0, "gross_sales_minor": 0, "refunded_minor": 0, "ticket_count": 0}
    )
    for day in sorted(order_trend):
        entry = order_trend[day]
        bucket = _bucket_period(day, period)
        target = bucket_trend[bucket]
        target["order_count"] += entry["order_count"]
        target["gross_sales_minor"] += entry["gross_sales_minor"]
        target["refunded_minor"] += entry["refunded_minor"]
        target["ticket_count"] += entry["ticket_count"]

    trend: list[TrendBucket] = []
    for bucket in sorted(bucket_trend):
        entry = bucket_trend[bucket]
        trend.append(
            TrendBucket(
                bucket=bucket,
                order_count=entry["order_count"],
                gross_sales_minor=entry["gross_sales_minor"],
                refunded_minor=entry["refunded_minor"],
                ticket_count=entry["ticket_count"],
            )
        )

    return MultiStoreSummaryResponse(
        store_id=None,
        start_at=start_at,
        end_at=end_at,
        period=period,
        currency=currency,
        stores=list(store_snapshots.values()),
        totals=totals,
        trend=trend,
    )


async def get_dashboard_kpi(
    session: AsyncSession,
    principal: Principal,
    *,
    store_ids: list[UUID] | None,
) -> DashboardKpiResponse:
    stores = await _resolve_report_stores(session, principal, store_ids)
    today = _business_timezone()
    business_date = datetime.now(today).date()
    currency = stores[0].currency if stores else "EUR"

    snapshots: list[DashboardKpiStore] = []
    totals = DashboardKpiStore(
        store_id=None,
        store_code=None,
        store_name=None,
        today_order_count=0,
        today_revenue_minor=0,
        open_tickets=0,
        open_manual_reviews=0,
        unknown_payments=0,
    )
    for store in stores:
        today_order_count = 0
        today_revenue_minor = 0
        row = (
            await session.execute(
                select(
                    func.count(SalesOrder.id),
                    func.coalesce(func.sum(SalesOrder.paid_minor), 0),
                    func.coalesce(func.sum(SalesOrder.refunded_minor), 0),
                ).where(
                    SalesOrder.store_id == store.id,
                    SalesOrder.tenant_id == principal.tenant_id,
                    SalesOrder.business_date == business_date,
                    SalesOrder.status.in_((OrderStatus.CONFIRMED, OrderStatus.CLOSED)),
                )
            )
        ).one()
        today_order_count = int(row[0])
        today_revenue_minor = int(row[1]) - int(row[2])

        open_tickets = int(
            await session.scalar(
                select(func.count(FulfillmentTicket.id))
                .join(SalesOrder, SalesOrder.id == FulfillmentTicket.order_id)
                .where(
                    SalesOrder.store_id == store.id,
                    FulfillmentTicket.status.not_in(
                        {
                            FulfillmentStatus.COLLECTED,
                            FulfillmentStatus.UNFULFILLABLE,
                            FulfillmentStatus.CANCELLED,
                        }
                    ),
                )
            )
            or 0
        )
        open_reviews = int(
            await session.scalar(
                select(func.count(ManualReviewCase.id)).where(
                    ManualReviewCase.store_id == store.id,
                    ManualReviewCase.status.not_in({ReviewStatus.RESOLVED, ReviewStatus.CLOSED}),
                )
            )
            or 0
        )
        unknown_payments = int(
            await session.scalar(
                select(func.count(PaymentAttempt.id))
                .join(SalesOrder, SalesOrder.id == PaymentAttempt.order_id)
                .where(
                    SalesOrder.store_id == store.id,
                    PaymentAttempt.status == PaymentStatus.UNKNOWN,
                )
            )
            or 0
        )
        snapshot = DashboardKpiStore(
            store_id=store.id,
            store_code=store.code,
            store_name=store.name,
            today_order_count=today_order_count,
            today_revenue_minor=today_revenue_minor,
            open_tickets=open_tickets,
            open_manual_reviews=open_reviews,
            unknown_payments=unknown_payments,
        )
        snapshots.append(snapshot)
        totals.today_order_count += snapshot.today_order_count
        totals.today_revenue_minor += snapshot.today_revenue_minor
        totals.open_tickets += snapshot.open_tickets
        totals.open_manual_reviews += snapshot.open_manual_reviews
        totals.unknown_payments += snapshot.unknown_payments

    return DashboardKpiResponse(
        business_date=business_date.isoformat(),
        currency=currency,
        stores=snapshots,
        totals=totals,
    )
