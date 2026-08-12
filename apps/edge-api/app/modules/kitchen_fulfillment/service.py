from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    FulfillmentFailureReason,
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    RefundStatus,
    ReviewStatus,
)
from app.core.errors import ConflictError, NotFoundError
from app.core.principals import FulfillmentEndpointPrincipal, Principal
from app.core.sensitive_data import contains_sensitive_card_data
from app.modules.audit.service import add_audit_log, add_outbox_event
from app.modules.kitchen_fulfillment.models import (
    FulfillmentEvent,
    FulfillmentTicket,
    FulfillmentTicketItem,
)
from app.modules.kitchen_fulfillment.schemas import (
    FulfillmentTicketItemResponse,
    FulfillmentTicketResponse,
)
from app.modules.manual_review.models import ManualReviewCase
from app.modules.ordering.models import OrderStatusEvent, SalesOrder
from app.modules.organization.models import FulfillmentEndpoint, KitchenStation
from app.modules.payments.models import Refund
from app.persistence.base import utc_now

SETTLED_PAYMENT_STATUSES = {
    PaymentStatus.PAID,
    PaymentStatus.REFUND_PENDING,
    PaymentStatus.PARTIALLY_REFUNDED,
    PaymentStatus.REFUNDED,
}

ALLOWED_TRANSITIONS: dict[FulfillmentStatus, frozenset[FulfillmentStatus]] = {
    FulfillmentStatus.QUEUED: frozenset(
        {
            FulfillmentStatus.ACKNOWLEDGED,
            FulfillmentStatus.ON_HOLD,
            FulfillmentStatus.UNFULFILLABLE,
        }
    ),
    FulfillmentStatus.ACKNOWLEDGED: frozenset(
        {
            FulfillmentStatus.PREPARING,
            FulfillmentStatus.ON_HOLD,
            FulfillmentStatus.UNFULFILLABLE,
        }
    ),
    FulfillmentStatus.PREPARING: frozenset(
        {
            FulfillmentStatus.READY,
            FulfillmentStatus.ON_HOLD,
            FulfillmentStatus.UNFULFILLABLE,
        }
    ),
    FulfillmentStatus.ON_HOLD: frozenset(
        {
            FulfillmentStatus.ACKNOWLEDGED,
            FulfillmentStatus.PREPARING,
            FulfillmentStatus.UNFULFILLABLE,
        }
    ),
    FulfillmentStatus.READY: frozenset({FulfillmentStatus.COLLECTED}),
}


async def heartbeat_endpoint(
    session: AsyncSession,
    endpoint: FulfillmentEndpointPrincipal,
) -> tuple[UUID, UUID, datetime, int]:
    endpoint_row = await session.scalar(
        select(FulfillmentEndpoint)
        .where(
            FulfillmentEndpoint.id == endpoint.endpoint_id,
            FulfillmentEndpoint.station_id == endpoint.station_id,
            FulfillmentEndpoint.active,
        )
        .with_for_update()
    )
    if endpoint_row is None:
        raise NotFoundError("fulfillment_endpoint", str(endpoint.endpoint_id))
    now = utc_now()
    endpoint_row.last_heartbeat_at = now
    endpoint_row.version += 1
    await session.flush()
    return endpoint_row.id, endpoint_row.station_id, now, endpoint_row.version


async def list_station_queue(
    session: AsyncSession,
    endpoint: FulfillmentEndpointPrincipal,
    principal: Principal,
) -> list[FulfillmentTicketResponse]:
    station = await session.get(KitchenStation, endpoint.station_id)
    if station is None or not station.active:
        raise NotFoundError("kitchen_station", str(endpoint.station_id))
    principal.require_store(station.store_id)
    tickets = list(
        (
            await session.scalars(
                select(FulfillmentTicket)
                .join(SalesOrder, SalesOrder.id == FulfillmentTicket.order_id)
                .where(
                    FulfillmentTicket.station_id == station.id,
                    SalesOrder.store_id == station.store_id,
                    FulfillmentTicket.status.in_(
                        {
                            FulfillmentStatus.QUEUED,
                            FulfillmentStatus.ACKNOWLEDGED,
                            FulfillmentStatus.PREPARING,
                            FulfillmentStatus.READY,
                            FulfillmentStatus.ON_HOLD,
                        }
                    ),
                )
                .order_by(
                    FulfillmentTicket.priority.desc(),
                    FulfillmentTicket.created_at,
                )
            )
        ).all()
    )
    return await build_ticket_responses(session, tickets)


async def transition_ticket(
    session: AsyncSession,
    endpoint: FulfillmentEndpointPrincipal,
    principal: Principal,
    *,
    ticket_id: UUID,
    to_status: FulfillmentStatus,
    expected_version: int,
    failure_reason_code: FulfillmentFailureReason | None,
    failure_detail: str | None,
) -> FulfillmentTicketResponse:
    ticket = await session.scalar(
        select(FulfillmentTicket)
        .where(
            FulfillmentTicket.id == ticket_id,
            FulfillmentTicket.station_id == endpoint.station_id,
        )
        .with_for_update()
    )
    if ticket is None:
        raise NotFoundError("fulfillment_ticket", str(ticket_id))
    station = await session.get(KitchenStation, ticket.station_id)
    if station is None:
        raise NotFoundError("kitchen_station", str(ticket.station_id))
    principal.require_store(station.store_id)
    if ticket.version != expected_version:
        raise ConflictError(
            "stale_version",
            "The fulfillment ticket was modified by another operator",
        )
    allowed = ALLOWED_TRANSITIONS.get(ticket.status, frozenset())
    if to_status not in allowed:
        raise ConflictError(
            "invalid_fulfillment_transition",
            f"The ticket cannot transition from {ticket.status} to {to_status}",
        )
    if to_status == FulfillmentStatus.UNFULFILLABLE and failure_reason_code is None:
        raise ConflictError(
            "failure_reason_required",
            "An explicit reason is required for an unfulfillable paid order",
        )
    if to_status != FulfillmentStatus.UNFULFILLABLE and (
        failure_reason_code is not None or failure_detail is not None
    ):
        raise ConflictError(
            "failure_detail_not_allowed",
            "Failure details are only valid for an unfulfillable ticket",
        )
    if failure_detail and contains_sensitive_card_data(failure_detail):
        raise ConflictError(
            "sensitive_data_rejected",
            "Fulfillment failure details must not contain cardholder authentication data",
        )

    order = await session.scalar(
        select(SalesOrder).where(SalesOrder.id == ticket.order_id).with_for_update()
    )
    if order is None:
        raise NotFoundError("sales_order", str(ticket.order_id))
    if order.store_id != station.store_id:
        raise ConflictError(
            "fulfillment_store_mismatch",
            "The fulfillment ticket and kitchen station must belong to the same store",
        )
    if (
        order.status != OrderStatus.CONFIRMED
        or order.payment_status not in SETTLED_PAYMENT_STATUSES
    ):
        raise ConflictError(
            "order_not_paid",
            "Only a confirmed paid order can enter manual fulfillment",
        )
    previous_status = ticket.status
    now = utc_now()
    ticket.status = to_status
    ticket.version += 1
    if to_status == FulfillmentStatus.ACKNOWLEDGED:
        ticket.acknowledged_by = principal.user_id
        ticket.acknowledged_at = now
    elif to_status == FulfillmentStatus.PREPARING:
        ticket.started_by = principal.user_id
        ticket.started_at = now
    elif to_status == FulfillmentStatus.READY:
        ticket.ready_by = principal.user_id
        ticket.ready_at = now
    elif to_status == FulfillmentStatus.COLLECTED:
        ticket.collected_by = principal.user_id
        ticket.collected_at = now
    elif to_status == FulfillmentStatus.UNFULFILLABLE:
        ticket.failure_reason_code = failure_reason_code
        ticket.failure_detail = failure_detail

    next_sequence = await session.scalar(
        select(func.coalesce(func.max(FulfillmentEvent.sequence_number), 0) + 1).where(
            FulfillmentEvent.ticket_id == ticket.id
        )
    )
    session.add(
        FulfillmentEvent(
            ticket_id=ticket.id,
            sequence_number=int(next_sequence or 1),
            from_status=previous_status,
            to_status=to_status,
            actor_type=ActorType.USER,
            actor_user_id=principal.user_id,
            actor_device_id=endpoint.endpoint_id,
            reason_code=failure_reason_code.value if failure_reason_code else None,
            metadata_json={"failure_detail": failure_detail} if failure_detail else {},
            occurred_at=now,
        )
    )
    add_audit_log(
        session,
        tenant_id=order.tenant_id,
        store_id=order.store_id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        actor_device_id=endpoint.endpoint_id,
        action="fulfillment.ticket.status_changed",
        target_type="fulfillment_ticket",
        target_id=ticket.id,
        before={"status": previous_status.value, "version": expected_version},
        after={"status": to_status.value, "version": ticket.version},
        occurred_at=now,
    )
    add_outbox_event(
        session,
        store_id=order.store_id,
        aggregate_type="fulfillment_ticket",
        aggregate_id=ticket.id,
        event_type="fulfillment.ticket.status_changed",
        payload={
            "ticket_id": str(ticket.id),
            "order_id": str(order.id),
            "from_status": previous_status.value,
            "to_status": to_status.value,
            "version": ticket.version,
        },
        deduplication_key=f"ticket-status:{ticket.id}:{ticket.version}",
        occurred_at=now,
    )

    if to_status == FulfillmentStatus.UNFULFILLABLE:
        assert failure_reason_code is not None
        existing_case = await session.scalar(
            select(ManualReviewCase).where(ManualReviewCase.fulfillment_ticket_id == ticket.id)
        )
        if existing_case is None:
            review_case = ManualReviewCase(
                store_id=order.store_id,
                order_id=order.id,
                fulfillment_ticket_id=ticket.id,
                case_number=f"MR-{ticket.id.hex.upper()}",
                status=ReviewStatus.OPEN,
                reason_code=failure_reason_code,
                priority=ticket.priority,
            )
            session.add(review_case)
            await session.flush()
            add_audit_log(
                session,
                tenant_id=order.tenant_id,
                store_id=order.store_id,
                actor_type=ActorType.USER,
                actor_user_id=principal.user_id,
                actor_device_id=endpoint.endpoint_id,
                action="manual_review.opened",
                target_type="manual_review_case",
                target_id=review_case.id,
                after={
                    "order_id": str(order.id),
                    "ticket_id": str(ticket.id),
                    "reason_code": failure_reason_code.value,
                    "status": review_case.status.value,
                },
                occurred_at=now,
            )
            add_outbox_event(
                session,
                store_id=order.store_id,
                aggregate_type="manual_review_case",
                aggregate_id=review_case.id,
                event_type="manual_review.opened",
                payload={
                    "case_id": str(review_case.id),
                    "order_id": str(order.id),
                    "ticket_id": str(ticket.id),
                    "reason_code": failure_reason_code.value,
                },
                deduplication_key=f"manual-review-opened:{review_case.id}",
                occurred_at=now,
            )

    await session.flush()
    if to_status == FulfillmentStatus.COLLECTED:
        await close_order_if_complete(session, order, actor_user_id=principal.user_id)
    responses = await build_ticket_responses(session, [ticket])
    return responses[0]


async def close_order_if_complete(
    session: AsyncSession,
    order: SalesOrder,
    *,
    actor_user_id: UUID | None,
) -> bool:
    if order.status != OrderStatus.CONFIRMED:
        return False
    open_ticket_count = await session.scalar(
        select(func.count(FulfillmentTicket.id)).where(
            FulfillmentTicket.order_id == order.id,
            FulfillmentTicket.status.not_in(
                {
                    FulfillmentStatus.COLLECTED,
                    FulfillmentStatus.UNFULFILLABLE,
                    FulfillmentStatus.CANCELLED,
                }
            ),
        )
    )
    open_review_count = await session.scalar(
        select(func.count(ManualReviewCase.id)).where(
            ManualReviewCase.order_id == order.id,
            ManualReviewCase.status.not_in({ReviewStatus.RESOLVED, ReviewStatus.CLOSED}),
        )
    )
    pending_refund_count = await session.scalar(
        select(func.count(Refund.id)).where(
            Refund.order_id == order.id,
            Refund.status.in_({RefundStatus.PENDING, RefundStatus.UNKNOWN}),
        )
    )
    if any(
        int(value or 0) > 0
        for value in (open_ticket_count, open_review_count, pending_refund_count)
    ):
        return False
    now = utc_now()
    order.status = OrderStatus.CLOSED
    order.closed_at = now
    order.version += 1
    next_sequence = await session.scalar(
        select(func.coalesce(func.max(OrderStatusEvent.sequence_number), 0) + 1).where(
            OrderStatusEvent.order_id == order.id
        )
    )
    session.add(
        OrderStatusEvent(
            order_id=order.id,
            sequence_number=int(next_sequence or 1),
            from_status=OrderStatus.CONFIRMED,
            to_status=OrderStatus.CLOSED,
            actor_type=ActorType.USER if actor_user_id else ActorType.SYSTEM,
            actor_user_id=actor_user_id,
            reason_code="FULFILLMENT_COMPLETE",
            occurred_at=now,
        )
    )
    add_audit_log(
        session,
        tenant_id=order.tenant_id,
        store_id=order.store_id,
        actor_type=ActorType.USER if actor_user_id else ActorType.SYSTEM,
        actor_user_id=actor_user_id,
        action="order.closed",
        target_type="sales_order",
        target_id=order.id,
        before={"status": OrderStatus.CONFIRMED.value},
        after={"status": OrderStatus.CLOSED.value, "version": order.version},
        occurred_at=now,
    )
    add_outbox_event(
        session,
        store_id=order.store_id,
        aggregate_type="sales_order",
        aggregate_id=order.id,
        event_type="order.closed",
        payload={"order_id": str(order.id), "version": order.version},
        deduplication_key=f"order-closed:{order.id}",
        occurred_at=now,
    )
    await session.flush()
    return True


async def build_ticket_responses(
    session: AsyncSession,
    tickets: list[FulfillmentTicket],
) -> list[FulfillmentTicketResponse]:
    ticket_ids = [ticket.id for ticket in tickets]
    items = list(
        (
            await session.scalars(
                select(FulfillmentTicketItem)
                .where(FulfillmentTicketItem.ticket_id.in_(ticket_ids))
                .order_by(FulfillmentTicketItem.ticket_id, FulfillmentTicketItem.id)
            )
        ).all()
    )
    items_by_ticket: dict[UUID, list[FulfillmentTicketItem]] = defaultdict(list)
    for item in items:
        items_by_ticket[item.ticket_id].append(item)
    return [
        FulfillmentTicketResponse(
            id=ticket.id,
            order_id=ticket.order_id,
            station_id=ticket.station_id,
            source_ticket_id=ticket.source_ticket_id,
            generation_number=ticket.generation_number,
            display_number=ticket.display_number,
            status=ticket.status,
            priority=ticket.priority,
            failure_reason_code=ticket.failure_reason_code,
            failure_detail=ticket.failure_detail,
            acknowledged_at=ticket.acknowledged_at,
            started_at=ticket.started_at,
            ready_at=ticket.ready_at,
            collected_at=ticket.collected_at,
            version=ticket.version,
            items=[
                FulfillmentTicketItemResponse(
                    order_item_id=item.order_item_id,
                    quantity=item.quantity,
                    name=item.name_snapshot,
                    preparation_snapshot=item.preparation_snapshot,
                    allergen_snapshot=item.allergen_snapshot,
                )
                for item in items_by_ticket[ticket.id]
            ],
        )
        for ticket in tickets
    ]
