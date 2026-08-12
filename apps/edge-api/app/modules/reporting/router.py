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
from app.modules.audit.models import OutboxEvent
from app.modules.kitchen_fulfillment.models import FulfillmentTicket
from app.modules.manual_review.models import ManualReviewCase
from app.modules.ordering.models import SalesOrder
from app.modules.payments.models import PaymentAttempt
from app.modules.reporting.schemas import (
    FulfillmentSummaryResponse,
    ReconciliationSummaryResponse,
    RefundSummaryResponse,
    SalesSummaryResponse,
    StoreOperationsSummary,
)
from app.modules.reporting.service import (
    get_fulfillment_summary,
    get_reconciliation_summary,
    get_refund_summary,
    get_sales_summary,
)

router = APIRouter(prefix="/admin/reports", tags=["admin-reports"])

ReportPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.REPORT_READ.value))
]
ReportTimestamp = Annotated[
    datetime,
    Query(description="Timezone-aware timestamp; the report window is [start_at, end_at)."),
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
    start_at: ReportTimestamp,
    end_at: ReportTimestamp,
    session: SessionDependency,
    principal: ReportPrincipal,
) -> SalesSummaryResponse:
    return await get_sales_summary(session, principal, store_id, start_at=start_at, end_at=end_at)


@router.get(
    "/refunds",
    response_model=RefundSummaryResponse,
    operation_id="get_refund_summary",
)
async def refund_summary(
    store_id: UUID,
    start_at: ReportTimestamp,
    end_at: ReportTimestamp,
    session: SessionDependency,
    principal: ReportPrincipal,
) -> RefundSummaryResponse:
    return await get_refund_summary(session, principal, store_id, start_at=start_at, end_at=end_at)


@router.get(
    "/fulfillment",
    response_model=FulfillmentSummaryResponse,
    operation_id="get_fulfillment_summary",
)
async def fulfillment_summary(
    store_id: UUID,
    start_at: ReportTimestamp,
    end_at: ReportTimestamp,
    session: SessionDependency,
    principal: ReportPrincipal,
) -> FulfillmentSummaryResponse:
    return await get_fulfillment_summary(
        session, principal, store_id, start_at=start_at, end_at=end_at
    )


@router.get(
    "/reconciliation",
    response_model=ReconciliationSummaryResponse,
    operation_id="get_reconciliation_summary",
)
async def reconciliation_summary(
    store_id: UUID,
    start_at: ReportTimestamp,
    end_at: ReportTimestamp,
    session: SessionDependency,
    principal: ReportPrincipal,
) -> ReconciliationSummaryResponse:
    return await get_reconciliation_summary(
        session, principal, store_id, start_at=start_at, end_at=end_at
    )
