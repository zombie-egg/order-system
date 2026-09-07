from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import Principal, SessionDependency, require_permission
from app.core.enums import (
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    PermissionCode,
    ReviewStatus,
)
from app.core.errors import DomainError
from app.modules.audit.models import OutboxEvent
from app.modules.kitchen_fulfillment.models import FulfillmentTicket
from app.modules.manual_review.models import ManualReviewCase
from app.modules.ordering.models import SalesOrder
from app.modules.payments.models import PaymentAttempt
from app.modules.reporting.schemas import (
    DashboardKpiResponse,
    FulfillmentSummaryResponse,
    MultiStoreSummaryResponse,
    ReconciliationSummaryResponse,
    RefundSummaryResponse,
    SalesSummaryResponse,
    StoreOperationsSummary,
    TopProductsResponse,
)
from app.modules.reporting.service import (
    get_dashboard_kpi,
    get_fulfillment_summary,
    get_multi_store_summary,
    get_reconciliation_summary,
    get_refund_summary,
    get_sales_summary,
    get_top_products,
    report_period_window,
)

router = APIRouter(prefix="/admin/reports", tags=["admin-reports"])

ReportPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.REPORT_READ.value))
]
OptionalReportTimestamp = Annotated[
    datetime | None,
    Query(description="Timezone-aware timestamp; the report window is [start_at, end_at)."),
]
OptionalStoreIds = Annotated[
    list[UUID] | None,
    Query(description="Restrict the report to these stores (defaults to the principal's stores)."),
]


async def _count(session: AsyncSession, statement: Select[Any]) -> int:
    value = await session.scalar(statement)
    return int(value or 0)


@router.get(
    "/operations",
    response_model=list[StoreOperationsSummary],
    operation_id="get_operations_summary",
)
async def get_operations_summary(
    session: SessionDependency,
    principal: ReportPrincipal,
) -> list[StoreOperationsSummary]:
    summaries: list[StoreOperationsSummary] = []
    for store_id in sorted(principal.store_ids, key=str):
        open_orders = await _count(
            session,
            select(func.count(SalesOrder.id)).where(
                SalesOrder.store_id == store_id,
                SalesOrder.status.in_({OrderStatus.DRAFT, OrderStatus.CONFIRMED}),
            ),
        )
        open_tickets = await _count(
            session,
            select(func.count(FulfillmentTicket.id))
            .join(SalesOrder, SalesOrder.id == FulfillmentTicket.order_id)
            .where(
                SalesOrder.store_id == store_id,
                FulfillmentTicket.status.not_in(
                    {
                        FulfillmentStatus.COLLECTED,
                        FulfillmentStatus.UNFULFILLABLE,
                        FulfillmentStatus.CANCELLED,
                    }
                ),
            ),
        )
        open_reviews = await _count(
            session,
            select(func.count(ManualReviewCase.id)).where(
                ManualReviewCase.store_id == store_id,
                ManualReviewCase.status.not_in({ReviewStatus.RESOLVED, ReviewStatus.CLOSED}),
            ),
        )
        unknown_payments = await _count(
            session,
            select(func.count(PaymentAttempt.id))
            .join(SalesOrder, SalesOrder.id == PaymentAttempt.order_id)
            .where(
                SalesOrder.store_id == store_id,
                PaymentAttempt.status == PaymentStatus.UNKNOWN,
            ),
        )
        paid_without_ticket = await _count(
            session,
            select(func.count(SalesOrder.id))
            .outerjoin(FulfillmentTicket, FulfillmentTicket.order_id == SalesOrder.id)
            .where(
                SalesOrder.store_id == store_id,
                SalesOrder.payment_status.in_(
                    {
                        PaymentStatus.PAID,
                        PaymentStatus.REFUND_PENDING,
                        PaymentStatus.PARTIALLY_REFUNDED,
                        PaymentStatus.REFUNDED,
                    }
                ),
                FulfillmentTicket.id.is_(None),
            ),
        )
        pending_outbox = await _count(
            session,
            select(func.count(OutboxEvent.id)).where(
                OutboxEvent.processed_at.is_(None),
                OutboxEvent.store_id == store_id,
            ),
        )
        summaries.append(
            StoreOperationsSummary(
                store_id=store_id,
                open_orders=open_orders,
                open_tickets=open_tickets,
                open_manual_reviews=open_reviews,
                unknown_payments=unknown_payments,
                paid_orders_without_tickets=paid_without_ticket,
                pending_outbox_events=pending_outbox,
            )
        )
    return summaries


@router.get(
    "/sales",
    response_model=SalesSummaryResponse,
    operation_id="get_sales_summary",
)
async def sales_summary(
    store_id: UUID,
    session: SessionDependency,
    principal: ReportPrincipal,
    range: Annotated[str | None, Query()] = None,
    start_at: OptionalReportTimestamp = None,
    end_at: OptionalReportTimestamp = None,
) -> SalesSummaryResponse:
    resolved_start, resolved_end = _resolve_window(start_at, end_at, range)
    return await get_sales_summary(
        session, principal, store_id, start_at=resolved_start, end_at=resolved_end
    )


@router.get(
    "/refunds",
    response_model=RefundSummaryResponse,
    operation_id="get_refund_summary",
)
async def refund_summary(
    store_id: UUID,
    session: SessionDependency,
    principal: ReportPrincipal,
    range: Annotated[str | None, Query()] = None,
    start_at: OptionalReportTimestamp = None,
    end_at: OptionalReportTimestamp = None,
) -> RefundSummaryResponse:
    resolved_start, resolved_end = _resolve_window(start_at, end_at, range)
    return await get_refund_summary(
        session, principal, store_id, start_at=resolved_start, end_at=resolved_end
    )


@router.get(
    "/fulfillment",
    response_model=FulfillmentSummaryResponse,
    operation_id="get_fulfillment_summary",
)
async def fulfillment_summary(
    store_id: UUID,
    session: SessionDependency,
    principal: ReportPrincipal,
    range: Annotated[str | None, Query()] = None,
    start_at: OptionalReportTimestamp = None,
    end_at: OptionalReportTimestamp = None,
) -> FulfillmentSummaryResponse:
    resolved_start, resolved_end = _resolve_window(start_at, end_at, range)
    return await get_fulfillment_summary(
        session, principal, store_id, start_at=resolved_start, end_at=resolved_end
    )


@router.get(
    "/reconciliation",
    response_model=ReconciliationSummaryResponse,
    operation_id="get_reconciliation_summary",
)
async def reconciliation_summary(
    store_id: UUID,
    session: SessionDependency,
    principal: ReportPrincipal,
    range: Annotated[str | None, Query()] = None,
    start_at: OptionalReportTimestamp = None,
    end_at: OptionalReportTimestamp = None,
) -> ReconciliationSummaryResponse:
    resolved_start, resolved_end = _resolve_window(start_at, end_at, range)
    return await get_reconciliation_summary(
        session, principal, store_id, start_at=resolved_start, end_at=resolved_end
    )


def _resolve_window(
    start_at: datetime | None, end_at: datetime | None, period: str | None
) -> tuple[datetime, datetime]:
    if period is not None:
        if start_at is not None or end_at is not None:
            raise DomainError(
                "overlapping_report_window",
                "Provide either a named period or an explicit start_at/end_at, not both",
            )
        return report_period_window(period)
    if start_at is None or end_at is None:
        raise DomainError(
            "missing_report_window",
            "Provide a named period or both start_at and end_at",
        )
    return start_at, end_at


@router.get(
    "/top-products",
    response_model=TopProductsResponse,
    operation_id="get_top_products_report",
)
async def top_products(
    session: SessionDependency,
    principal: ReportPrincipal,
    store_ids: OptionalStoreIds = None,
    order_by: Annotated[str, Query(pattern="^(quantity|revenue)$")] = "quantity",
    limit: Annotated[int, Query(ge=1, le=100)] = 5,
    locale: Annotated[str, Query(min_length=2, max_length=20)] = "nl-NL",
    range: Annotated[str | None, Query()] = None,
    start_at: Annotated[datetime | None, Query()] = None,
    end_at: Annotated[datetime | None, Query()] = None,
) -> TopProductsResponse:
    resolved_start, resolved_end = _resolve_window(start_at, end_at, range)
    return await get_top_products(
        session,
        principal,
        store_ids=store_ids,
        start_at=resolved_start,
        end_at=resolved_end,
        order_by=order_by,
        limit=limit,
        locale=locale,
    )


@router.get(
    "/multi-store",
    response_model=MultiStoreSummaryResponse,
    operation_id="get_multi_store_report",
)
async def multi_store_summary(
    session: SessionDependency,
    principal: ReportPrincipal,
    store_ids: OptionalStoreIds = None,
    period: Annotated[str, Query(pattern="^(day|week|month)$")] = "day",
    range: Annotated[str | None, Query()] = None,
    start_at: OptionalReportTimestamp = None,
    end_at: OptionalReportTimestamp = None,
) -> MultiStoreSummaryResponse:
    if (start_at is None) != (end_at is None):
        raise DomainError(
            "incomplete_report_window",
            "Provide both start_at and end_at",
        )
    window_period: str | None = range or "this_week"
    if start_at is not None:
        window_period = None
    resolved_start, resolved_end = _resolve_window(start_at, end_at, window_period)
    return await get_multi_store_summary(
        session,
        principal,
        store_ids=store_ids,
        start_at=resolved_start,
        end_at=resolved_end,
        period=period,
    )


@router.get(
    "/dashboard",
    response_model=DashboardKpiResponse,
    operation_id="get_dashboard_kpi",
)
async def dashboard_kpi(
    session: SessionDependency,
    principal: ReportPrincipal,
    store_ids: OptionalStoreIds = None,
) -> DashboardKpiResponse:
    return await get_dashboard_kpi(session, principal, store_ids=store_ids)
