from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    FulfillmentStatus,
    IdempotencyStatus,
    PaymentStatus,
    PermissionCode,
    RefundStatus,
    ReviewResolution,
    ReviewStatus,
)
from app.core.errors import ConflictError, NotFoundError
from app.core.principals import Principal
from app.modules.audit.service import (
    acquire_idempotency_record,
    add_audit_log,
    add_outbox_event,
    complete_idempotency_record,
)
from app.modules.identity.models import Permission, Role, RolePermission, UserAccount, UserStoreRole
from app.modules.kitchen_fulfillment.models import (
    FulfillmentEvent,
    FulfillmentTicket,
    FulfillmentTicketItem,
)
from app.modules.kitchen_fulfillment.service import close_order_if_complete
from app.modules.manual_review.models import ManualReviewAction, ManualReviewCase
from app.modules.manual_review.schemas import ManualReviewResponse, ResolveReviewRequest
from app.modules.ordering.models import SalesOrder
from app.modules.payments.models import PaymentAttempt, Refund
from app.persistence.base import utc_now


async def list_reviews(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int,
) -> list[ManualReviewResponse]:
    if not principal.store_ids:
        return []
    cases = list(
        (
            await session.scalars(
                select(ManualReviewCase)
                .where(ManualReviewCase.store_id.in_(principal.store_ids))
                .order_by(
                    ManualReviewCase.priority.desc(),
                    ManualReviewCase.created_at,
                )
                .limit(limit)
            )
        ).all()
    )
    return [to_review_response(case) for case in cases]


async def assign_review(
    session: AsyncSession,
    principal: Principal,
    *,
    case_id: UUID,
    assignee_user_id: UUID | None,
    expected_version: int,
) -> ManualReviewResponse:
    case = await session.scalar(
        select(ManualReviewCase).where(ManualReviewCase.id == case_id).with_for_update()
    )
    if case is None:
        raise NotFoundError("manual_review_case", str(case_id))
    principal.require_store(case.store_id)
    if case.version != expected_version:
        raise ConflictError("stale_version", "The review case was modified by another user")
    if case.status in {ReviewStatus.RESOLVED, ReviewStatus.CLOSED}:
        raise ConflictError("review_already_resolved", "The review case is already resolved")
    if case.status == ReviewStatus.ACTION_PENDING:
        raise ConflictError(
            "review_action_pending",
            "The current review action must finish before the case can be reassigned",
        )
    assignee_id = assignee_user_id or principal.user_id
    assignee = await session.scalar(
        select(UserAccount)
        .join(UserStoreRole, UserStoreRole.user_id == UserAccount.id)
        .join(Role, Role.id == UserStoreRole.role_id)
        .join(RolePermission, RolePermission.role_id == UserStoreRole.role_id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            UserAccount.id == assignee_id,
            UserAccount.tenant_id == principal.tenant_id,
            UserAccount.active,
            UserStoreRole.store_id == case.store_id,
            Role.tenant_id == principal.tenant_id,
            Permission.code == PermissionCode.REVIEW_RESOLVE.value,
        )
    )
    if assignee is None:
        raise ConflictError(
            "review_assignee_not_eligible",
            "The assignee must be an active reviewer for this store",
        )
    now = utc_now()
    case.assigned_to = assignee.id
    case.assigned_at = now
    case.status = ReviewStatus.ASSIGNED
    case.version += 1
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=case.store_id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="manual_review.assigned",
        target_type="manual_review_case",
        target_id=case.id,
        after={"assigned_to": str(assignee.id), "version": case.version},
        occurred_at=now,
    )
    await session.flush()
    return to_review_response(case)


async def resolve_review(
    session: AsyncSession,
    principal: Principal,
    *,
    case_id: UUID,
    request: ResolveReviewRequest,
    idempotency_key: str,
) -> ManualReviewResponse:
    record, created = await acquire_idempotency_record(
        session,
        namespace="resolve_manual_review",
        actor_scope=str(principal.user_id),
        idempotency_key=idempotency_key,
        request_payload={"case_id": str(case_id), **request.model_dump(mode="json")},
    )
    if not created:
        if record.status == IdempotencyStatus.COMPLETED and record.resource_id is not None:
            existing = await session.get(ManualReviewCase, record.resource_id)
            if existing is None:
                raise NotFoundError("manual_review_case", str(record.resource_id))
            principal.require_store(existing.store_id)
            return to_review_response(existing)
        raise ConflictError(
            "idempotency_request_in_progress",
            "A request with this Idempotency-Key is still being processed",
        )

    case = await session.scalar(
        select(ManualReviewCase).where(ManualReviewCase.id == case_id).with_for_update()
    )
    if case is None:
        raise NotFoundError("manual_review_case", str(case_id))
    principal.require_store(case.store_id)
    if case.version != request.expected_version:
        raise ConflictError("stale_version", "The review case was modified by another user")
    if case.status in {ReviewStatus.RESOLVED, ReviewStatus.CLOSED}:
        raise ConflictError("review_already_resolved", "The review case is already resolved")
    if case.status == ReviewStatus.ACTION_PENDING:
        raise ConflictError(
            "review_action_pending",
            "The current review action must finish before another resolution is requested",
        )
    if case.assigned_to not in {None, principal.user_id}:
        raise ConflictError("review_assigned_elsewhere", "The review is assigned to another user")

    order = await session.scalar(
        select(SalesOrder).where(SalesOrder.id == case.order_id).with_for_update()
    )
    ticket = (
        await session.get(FulfillmentTicket, case.fulfillment_ticket_id)
        if case.fulfillment_ticket_id is not None
        else None
    )
    if order is None:
        raise ConflictError(
            "review_source_missing",
            "The order for this review is unavailable",
        )
    if order.tenant_id != principal.tenant_id or order.store_id != case.store_id:
        raise ConflictError(
            "review_source_mismatch",
            "The review source does not match an unfulfillable paid order",
        )
    if case.fulfillment_ticket_id is not None and (
        ticket is None
        or ticket.order_id != order.id
        or ticket.status != FulfillmentStatus.UNFULFILLABLE
    ):
        raise ConflictError(
            "review_source_mismatch",
            "The review source does not match an unfulfillable paid order",
        )
    if ticket is None and request.resolution in {
        ReviewResolution.REMAKE,
        ReviewResolution.SUBSTITUTION,
    }:
        raise ConflictError(
            "fulfillment_ticket_required",
            "A remake or substitution requires a configured fulfillment station",
        )
    now = utc_now()
    case.assigned_to = principal.user_id
    case.assigned_at = case.assigned_at or now
    case.resolution_code = request.resolution
    case.version += 1
    next_action_sequence = await session.scalar(
        select(func.coalesce(func.max(ManualReviewAction.sequence_number), 0) + 1).where(
            ManualReviewAction.case_id == case.id
        )
    )
    action = ManualReviewAction(
        case_id=case.id,
        sequence_number=int(next_action_sequence or 1),
        action_type=request.resolution,
        actor_user_id=principal.user_id,
        notes=request.notes,
        payload=request.payload,
        occurred_at=now,
    )
    session.add(action)
    await session.flush()

    if request.resolution in {
        ReviewResolution.FULL_REFUND,
        ReviewResolution.PARTIAL_REFUND,
    }:
        await _request_refund(
            session,
            case=case,
            action=action,
            order=order,
            principal=principal,
            resolution=request.resolution,
            partial_amount_minor=request.refund_amount_minor,
            request_key_hash=record.idempotency_key,
        )
    elif request.resolution in {ReviewResolution.REMAKE, ReviewResolution.SUBSTITUTION}:
        assert ticket is not None
        new_ticket = await _create_replacement_ticket(
            session,
            original=ticket,
            order=order,
            principal=principal,
            preparation_override=(
                request.payload if request.resolution == ReviewResolution.SUBSTITUTION else None
            ),
        )
        action.related_ticket_id = new_ticket.id
        case.status = ReviewStatus.RESOLVED
        case.resolved_at = now
    else:
        case.status = ReviewStatus.RESOLVED
        case.resolved_at = now

    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=case.store_id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="manual_review.resolution_requested",
        target_type="manual_review_case",
        target_id=case.id,
        after={
            "status": case.status.value,
            "resolution": request.resolution.value,
            "version": case.version,
        },
        occurred_at=now,
    )
    add_outbox_event(
        session,
        store_id=case.store_id,
        aggregate_type="manual_review_case",
        aggregate_id=case.id,
        event_type="manual_review.action_recorded",
        payload={
            "case_id": str(case.id),
            "order_id": str(order.id),
            "resolution": request.resolution.value,
            "status": case.status.value,
        },
        deduplication_key=f"manual-review-action:{action.id}",
        occurred_at=now,
    )
    await session.flush()
    if case.status == ReviewStatus.RESOLVED:
        await close_order_if_complete(session, order, actor_user_id=principal.user_id)
    complete_idempotency_record(
        record,
        resource_type="manual_review_case",
        resource_id=case.id,
        response_status=200,
        response_json={"case_id": str(case.id), "status": case.status.value},
    )
    return to_review_response(case)


async def _request_refund(
    session: AsyncSession,
    *,
    case: ManualReviewCase,
    action: ManualReviewAction,
    order: SalesOrder,
    principal: Principal,
    resolution: ReviewResolution,
    partial_amount_minor: int | None,
    request_key_hash: str,
) -> Refund:
    attempt = await session.scalar(
        select(PaymentAttempt)
        .where(
            PaymentAttempt.order_id == order.id,
            PaymentAttempt.psp_reference.is_not(None),
            PaymentAttempt.status.in_(
                {
                    PaymentStatus.PAID,
                    PaymentStatus.PARTIALLY_REFUNDED,
                    PaymentStatus.REFUNDED,
                    PaymentStatus.REFUND_PENDING,
                }
            ),
        )
        .order_by(PaymentAttempt.attempt_number.desc())
        .with_for_update()
    )
    if attempt is None:
        raise ConflictError("refundable_payment_missing", "No confirmed payment can be refunded")
    remaining = order.paid_minor - order.refunded_minor
    amount = remaining if resolution == ReviewResolution.FULL_REFUND else partial_amount_minor
    if amount is None or amount <= 0 or amount > remaining:
        raise ConflictError(
            "invalid_refund_amount",
            "The requested refund must be positive and cannot exceed the remaining paid amount",
        )
    pending_total = await session.scalar(
        select(func.coalesce(func.sum(Refund.amount_minor), 0)).where(
            Refund.order_id == order.id,
            Refund.status.in_({RefundStatus.PENDING, RefundStatus.UNKNOWN}),
        )
    )
    if int(pending_total or 0) + amount > remaining:
        raise ConflictError(
            "refund_exceeds_available_amount",
            "Another pending refund reserves part of the remaining paid amount",
        )
    refund = Refund(
        order_id=order.id,
        payment_attempt_id=attempt.id,
        request_key_hash=request_key_hash,
        amount_minor=amount,
        currency=order.currency,
        reason_code=case.reason_code.value,
        status=RefundStatus.PENDING,
        requested_by=principal.user_id,
    )
    session.add(refund)
    await session.flush()
    action.related_refund_id = refund.id
    case.status = ReviewStatus.ACTION_PENDING
    order.payment_status = PaymentStatus.REFUND_PENDING
    order.version += 1
    attempt.status = PaymentStatus.REFUND_PENDING
    attempt.version += 1
    return refund


async def _create_replacement_ticket(
    session: AsyncSession,
    *,
    original: FulfillmentTicket,
    order: SalesOrder,
    principal: Principal,
    preparation_override: dict[str, object] | None,
) -> FulfillmentTicket:
    latest_generation = await session.scalar(
        select(func.coalesce(func.max(FulfillmentTicket.generation_number), 0)).where(
            FulfillmentTicket.order_id == original.order_id,
            FulfillmentTicket.station_id == original.station_id,
        )
    )
    generation = int(latest_generation or 0) + 1
    now = utc_now()
    snapshot = dict(original.preparation_snapshot)
    if preparation_override:
        snapshot["manual_substitution"] = preparation_override
    replacement = FulfillmentTicket(
        order_id=original.order_id,
        station_id=original.station_id,
        source_ticket_id=original.id,
        generation_number=generation,
        display_number=original.display_number,
        status=FulfillmentStatus.QUEUED,
        priority=original.priority,
        preparation_snapshot=snapshot,
    )
    session.add(replacement)
    await session.flush()
    original_items = list(
        (
            await session.scalars(
                select(FulfillmentTicketItem).where(FulfillmentTicketItem.ticket_id == original.id)
            )
        ).all()
    )
    session.add_all(
        FulfillmentTicketItem(
            ticket_id=replacement.id,
            order_item_id=item.order_item_id,
            quantity=item.quantity,
            name_snapshot=item.name_snapshot,
            preparation_snapshot=(
                {**item.preparation_snapshot, "manual_substitution": preparation_override}
                if preparation_override
                else item.preparation_snapshot
            ),
            allergen_snapshot=item.allergen_snapshot,
        )
        for item in original_items
    )
    session.add(
        FulfillmentEvent(
            ticket_id=replacement.id,
            sequence_number=1,
            from_status=None,
            to_status=FulfillmentStatus.QUEUED,
            actor_type=ActorType.USER,
            actor_user_id=principal.user_id,
            reason_code="MANUAL_REVIEW_REPLACEMENT",
            occurred_at=now,
        )
    )
    add_outbox_event(
        session,
        store_id=order.store_id,
        aggregate_type="fulfillment_ticket",
        aggregate_id=replacement.id,
        event_type="fulfillment.ticket.created",
        payload={
            "ticket_id": str(replacement.id),
            "order_id": str(order.id),
            "source_ticket_id": str(original.id),
            "generation_number": generation,
        },
        deduplication_key=f"ticket-created:{replacement.id}",
        occurred_at=now,
    )
    return replacement


def to_review_response(case: ManualReviewCase) -> ManualReviewResponse:
    return ManualReviewResponse(
        id=case.id,
        store_id=case.store_id,
        order_id=case.order_id,
        fulfillment_ticket_id=case.fulfillment_ticket_id,
        case_number=case.case_number,
        status=case.status,
        reason_code=case.reason_code,
        priority=case.priority,
        assigned_to=case.assigned_to,
        resolution_code=case.resolution_code,
        assigned_at=case.assigned_at,
        resolved_at=case.resolved_at,
        closed_at=case.closed_at,
        version=case.version,
    )
