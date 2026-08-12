from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FulfillmentStatus, OrderStatus, RefundStatus
from app.core.errors import DomainError
from app.core.principals import Principal
from app.modules.kitchen_fulfillment.models import FulfillmentTicket
from app.modules.ordering.models import SalesOrder
from app.modules.organization.service import get_store_for_tenant
from app.modules.payments.models import ReconciliationIssue, ReconciliationRun, Refund
from app.modules.reporting.schemas import (
    FulfillmentSummaryResponse,
    ReconciliationSummaryResponse,
    RefundSummaryResponse,
    SalesSummaryResponse,
)


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
