from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    FulfillmentFailureReason,
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    PaymentTransactionKind,
    RefundStatus,
    ReviewStatus,
)
from app.core.errors import ConflictError, DomainError, NotFoundError
from app.core.principals import Principal
from app.modules.audit.service import add_audit_log, add_outbox_event, canonical_json_hash
from app.modules.kitchen_fulfillment.models import (
    FulfillmentEvent,
    FulfillmentTicket,
    FulfillmentTicketItem,
)
from app.modules.kitchen_fulfillment.service import close_order_if_complete
from app.modules.manual_review.models import ManualReviewAction, ManualReviewCase
from app.modules.ordering.models import OrderItem, OrderStatusEvent, SalesOrder
from app.modules.ordering.schemas import OrderResponse
from app.modules.ordering.service import build_order_response
from app.modules.organization.models import KitchenStation, PaymentTerminal
from app.modules.payments.models import PaymentAttempt, PaymentTransaction, Refund
from app.modules.payments.providers import (
    AuthorizationResult,
    AuthorizeCommand,
    PaymentAdapter,
    RefundCommand,
    RefundResult,
)
from app.modules.payments.sanitization import (
    sanitize_masked_account,
    sanitize_provider_identifier,
    sanitize_provider_text,
)
from app.modules.payments.schemas import RefundResponse
from app.modules.receipts.service import create_refund_receipt, create_sale_receipt
from app.persistence.base import utc_now
from app.persistence.database import Database

SETTLED_PAYMENT_STATUSES = {
    PaymentStatus.PAID,
    PaymentStatus.REFUND_PENDING,
    PaymentStatus.PARTIALLY_REFUNDED,
    PaymentStatus.REFUNDED,
}


async def execute_authorization(
    database: Database,
    adapter: PaymentAdapter,
    *,
    kiosk_id: UUID,
    attempt_id: UUID,
    reconcile: bool = False,
) -> OrderResponse:
    if not adapter.available:
        raise DomainError(
            "payment_adapter_unavailable",
            "No approved payment adapter is configured",
            status_code=503,
        )

    command: AuthorizeCommand | None = None
    use_query = reconcile
    async with database.session_factory() as session, session.begin():
        row = (
            await session.execute(
                select(PaymentAttempt, SalesOrder, PaymentTerminal)
                .join(SalesOrder, SalesOrder.id == PaymentAttempt.order_id)
                .join(PaymentTerminal, PaymentTerminal.id == PaymentAttempt.terminal_id)
                .where(PaymentAttempt.id == attempt_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("payment_attempt", str(attempt_id))
        attempt, order, terminal = row
        if order.kiosk_id != kiosk_id:
            raise NotFoundError("payment_attempt", str(attempt_id))
        if attempt.provider != adapter.provider:
            raise DomainError(
                "payment_adapter_mismatch",
                "The configured adapter cannot process this payment attempt",
                status_code=503,
            )
        if attempt.amount_minor != order.total_minor or attempt.currency != order.currency:
            raise ConflictError(
                "payment_order_amount_mismatch",
                "The payment attempt amount or currency no longer matches the order",
            )
        if attempt.status in {PaymentStatus.PAID, PaymentStatus.FAILED}:
            if reconcile:
                raise ConflictError(
                    "payment_not_reconcilable",
                    "Only authorizing or unknown payment attempts can be reconciled",
                )
            return await build_order_response(session, order)
        if attempt.status == PaymentStatus.UNKNOWN and not reconcile:
            raise ConflictError(
                "payment_result_unknown",
                "The payment result is unknown; reconcile this attempt instead of paying again",
            )
        if reconcile and attempt.status not in {
            PaymentStatus.AUTHORIZING,
            PaymentStatus.UNKNOWN,
        }:
            raise ConflictError(
                "payment_not_reconcilable",
                "Only authorizing or unknown payment attempts can be reconciled",
            )
        use_query = reconcile or attempt.status == PaymentStatus.AUTHORIZING
        attempt.status = PaymentStatus.AUTHORIZING
        attempt.version += 1
        command = AuthorizeCommand(
            attempt_id=attempt.id,
            provider_service_id=attempt.provider_service_id,
            merchant_reference=attempt.merchant_reference,
            terminal_reference=terminal.terminal_reference,
            amount_minor=attempt.amount_minor,
            currency=attempt.currency,
        )

    assert command is not None
    try:
        result = (
            await adapter.query_authorization(command)
            if use_query
            else await adapter.authorize(command)
        )
    except DomainError:
        raise
    except Exception as exc:
        result = AuthorizationResult(
            provider=adapter.provider,
            provider_event_id=f"local-unknown-{uuid4()}",
            status=PaymentStatus.UNKNOWN,
            failure_code="ADAPTER_EXCEPTION",
            failure_detail_redacted=type(exc).__name__,
        )
    return await apply_authorization_result(database, attempt_id=attempt_id, result=result)


async def apply_authorization_result(
    database: Database,
    *,
    attempt_id: UUID,
    result: AuthorizationResult,
) -> OrderResponse:
    if result.status not in {
        PaymentStatus.PAID,
        PaymentStatus.FAILED,
        PaymentStatus.UNKNOWN,
    }:
        raise ValueError("An authorization result must be PAID, FAILED, or UNKNOWN")
    async with database.session_factory() as session, session.begin():
        row = (
            await session.execute(
                select(PaymentAttempt, SalesOrder)
                .join(SalesOrder, SalesOrder.id == PaymentAttempt.order_id)
                .where(PaymentAttempt.id == attempt_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("payment_attempt", str(attempt_id))
        attempt, order = row
        if attempt.provider != result.provider:
            raise ConflictError(
                "payment_provider_mismatch",
                "The payment result provider does not match the attempt",
            )
        if attempt.amount_minor != order.total_minor or attempt.currency != order.currency:
            raise ConflictError(
                "payment_order_amount_mismatch",
                "The payment attempt amount or currency no longer matches the order",
            )
        provider_event_id = sanitize_provider_identifier(
            result.provider_event_id,
            fallback_scope=f"authorization:{attempt.id}",
        )
        safe_psp_reference = sanitize_provider_text(result.psp_reference, maximum_length=160)
        safe_card_brand = sanitize_provider_text(result.card_brand, maximum_length=40)
        safe_masked_account = sanitize_masked_account(result.masked_account)
        safe_failure_code = sanitize_provider_text(result.failure_code, maximum_length=100)
        safe_failure_detail = sanitize_provider_text(
            result.failure_detail_redacted,
            maximum_length=500,
        )
        payload_hash = canonical_json_hash(
            {
                "attempt_id": str(attempt.id),
                "provider": result.provider.value,
                "provider_event_id": provider_event_id,
                "status": result.status.value,
                "psp_reference": safe_psp_reference,
                "card_brand": safe_card_brand,
                "masked_account": safe_masked_account,
                "failure_code": safe_failure_code,
                "failure_detail_redacted": safe_failure_detail,
            }
        )
        if attempt.status == PaymentStatus.FAILED and result.status != PaymentStatus.FAILED:
            raise ConflictError(
                "payment_attempt_terminal",
                "A failed payment attempt cannot transition to another terminal result",
            )
        existing_transaction = await session.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.provider == result.provider,
                PaymentTransaction.provider_event_id == provider_event_id,
            )
        )
        is_new_transaction = existing_transaction is None
        if existing_transaction is not None:
            if (
                existing_transaction.attempt_id != attempt.id
                or existing_transaction.transaction_kind != PaymentTransactionKind.AUTHORISATION
                or existing_transaction.amount_minor != attempt.amount_minor
                or existing_transaction.currency != attempt.currency
                or existing_transaction.payload_hash != payload_hash
            ):
                raise ConflictError(
                    "payment_event_conflict",
                    "The provider event was already recorded for different payment data",
                )
        else:
            transaction_time = utc_now()
            session.add(
                PaymentTransaction(
                    attempt_id=attempt.id,
                    provider=result.provider,
                    transaction_kind=PaymentTransactionKind.AUTHORISATION,
                    status=result.status,
                    amount_minor=attempt.amount_minor,
                    currency=attempt.currency,
                    provider_event_id=provider_event_id,
                    psp_reference=safe_psp_reference,
                    occurred_at=transaction_time,
                    received_at=transaction_time,
                    payload_hash=payload_hash,
                    payload_redacted={
                        "status": result.status.value,
                        "failure_code": safe_failure_code,
                    },
                )
            )

        if attempt.status in SETTLED_PAYMENT_STATUSES:
            return await build_order_response(session, order)
        if order.status != OrderStatus.DRAFT:
            raise ConflictError(
                "order_not_payable",
                "Only a draft order can accept an authorization result",
            )
        if attempt.status == result.status and order.payment_status == result.status:
            return await build_order_response(session, order)

        now = utc_now()
        attempt.status = result.status
        if safe_psp_reference is not None:
            attempt.psp_reference = safe_psp_reference
        if safe_card_brand is not None:
            attempt.card_brand = safe_card_brand
        if safe_masked_account is not None:
            attempt.masked_account = safe_masked_account
        attempt.failure_code = safe_failure_code
        attempt.failure_detail_redacted = safe_failure_detail
        attempt.completed_at = now if result.status != PaymentStatus.UNKNOWN else None
        attempt.last_status_check_at = now
        attempt.version += 1

        if result.status == PaymentStatus.PAID:
            await _confirm_paid_order(session, order, attempt, now=now)
        else:
            if order.payment_status != result.status:
                order.payment_status = result.status
                order.version += 1
            if is_new_transaction:
                add_audit_log(
                    session,
                    tenant_id=order.tenant_id,
                    store_id=order.store_id,
                    actor_type=ActorType.PROVIDER,
                    action="payment.status_changed",
                    target_type="payment_attempt",
                    target_id=attempt.id,
                    actor_device_id=order.kiosk_id,
                    after={"status": result.status.value, "failure_code": safe_failure_code},
                    occurred_at=now,
                )
                add_outbox_event(
                    session,
                    store_id=order.store_id,
                    aggregate_type="payment_attempt",
                    aggregate_id=attempt.id,
                    event_type="payment.status_changed",
                    payload={
                        "attempt_id": str(attempt.id),
                        "order_id": str(order.id),
                        "status": result.status.value,
                    },
                    deduplication_key=(
                        f"payment-status:{attempt.id}:{canonical_json_hash(provider_event_id)}"
                    ),
                    occurred_at=now,
                )
        await session.flush()
        return await build_order_response(session, order)


async def _confirm_paid_order(
    session: AsyncSession,
    order: SalesOrder,
    attempt: PaymentAttempt,
    *,
    now: datetime,
) -> None:
    if order.status == OrderStatus.CONFIRMED and order.payment_status == PaymentStatus.PAID:
        return
    if order.status != OrderStatus.DRAFT:
        raise ConflictError(
            "order_not_payable",
            "Only a draft order can be confirmed by payment",
        )
    stations = list(
        (
            await session.scalars(
                select(KitchenStation)
                .where(KitchenStation.store_id == order.store_id)
                .order_by(
                    KitchenStation.active.desc(),
                    KitchenStation.is_default.desc(),
                    KitchenStation.id,
                )
            )
        ).all()
    )
    active_default_stations = [
        station for station in stations if station.active and station.is_default
    ]
    release_issue: str | None = None
    station: KitchenStation | None
    if len(active_default_stations) == 1:
        station = active_default_stations[0]
    else:
        # A provider-confirmed payment is an external fact and must never be rolled back
        # because kitchen configuration changed while the terminal request was in flight.
        # A deterministic station is used only as an exception-case anchor; the ticket is
        # terminal and is not released into the preparation queue.
        station = stations[0] if stations else None
        release_issue = (
            "ACTIVE_DEFAULT_STATION_MISSING"
            if not active_default_stations
            else "ACTIVE_DEFAULT_STATION_AMBIGUOUS"
        )
    order.status = OrderStatus.CONFIRMED
    order.payment_status = PaymentStatus.PAID
    order.paid_minor = attempt.amount_minor
    order.confirmed_at = now
    order.version += 1
    session.add(
        OrderStatusEvent(
            order_id=order.id,
            sequence_number=2,
            from_status=OrderStatus.DRAFT,
            to_status=OrderStatus.CONFIRMED,
            actor_type=ActorType.PROVIDER,
            reason_code="PAYMENT_CONFIRMED",
            occurred_at=now,
        )
    )
    ticket: FulfillmentTicket | None = None
    review_case: ManualReviewCase | None = None
    order_items = list(
        (
            await session.scalars(
                select(OrderItem)
                .where(OrderItem.order_id == order.id)
                .order_by(OrderItem.line_number)
            )
        ).all()
    )
    if station is not None:
        ticket = await session.scalar(
            select(FulfillmentTicket).where(
                FulfillmentTicket.order_id == order.id,
                FulfillmentTicket.station_id == station.id,
                FulfillmentTicket.generation_number == 1,
            )
        )
    if station is not None and ticket is None:
        ticket_status = (
            FulfillmentStatus.QUEUED if release_issue is None else FulfillmentStatus.UNFULFILLABLE
        )
        ticket = FulfillmentTicket(
            order_id=order.id,
            station_id=station.id,
            generation_number=1,
            display_number=order.display_number,
            status=ticket_status,
            priority=0,
            preparation_snapshot={
                "schema_version": 1,
                "order_id": str(order.id),
                "item_count": len(order_items),
                "release_issue": release_issue,
                "fulfillment_type": order.fulfillment_type.value,
            },
            failure_reason_code=(
                FulfillmentFailureReason.MANUAL_WORKSTATION_EQUIPMENT_FAILURE
                if release_issue is not None
                else None
            ),
            failure_detail=(
                "Paid order held for manual review because no single active default "
                "kitchen station was available."
                if release_issue is not None
                else None
            ),
        )
        session.add(ticket)
        await session.flush()
        session.add_all(
            FulfillmentTicketItem(
                ticket_id=ticket.id,
                order_item_id=item.id,
                quantity=item.quantity,
                name_snapshot=item.name_snapshot,
                preparation_snapshot=item.preparation_snapshot,
                allergen_snapshot=item.allergen_snapshot,
            )
            for item in order_items
        )
        session.add(
            FulfillmentEvent(
                ticket_id=ticket.id,
                sequence_number=1,
                from_status=None,
                to_status=ticket_status,
                actor_type=ActorType.SYSTEM,
                reason_code=("PAYMENT_CONFIRMED" if release_issue is None else release_issue),
                occurred_at=now,
            )
        )
    if release_issue is not None:
        review_anchor_id = ticket.id if ticket is not None else order.id
        review_case = ManualReviewCase(
            store_id=order.store_id,
            order_id=order.id,
            fulfillment_ticket_id=ticket.id if ticket is not None else None,
            case_number=f"MR-{review_anchor_id.hex.upper()}",
            status=ReviewStatus.OPEN,
            reason_code=FulfillmentFailureReason.MANUAL_WORKSTATION_EQUIPMENT_FAILURE,
            priority=ticket.priority if ticket is not None else 100,
        )
        session.add(review_case)
        await session.flush()
        review_payload = {
            "case_id": str(review_case.id),
            "order_id": str(order.id),
            "ticket_id": str(ticket.id) if ticket is not None else None,
            "reason_code": (FulfillmentFailureReason.MANUAL_WORKSTATION_EQUIPMENT_FAILURE.value),
            "release_issue": release_issue,
        }
        add_audit_log(
            session,
            tenant_id=order.tenant_id,
            store_id=order.store_id,
            actor_type=ActorType.SYSTEM,
            action="manual_review.opened",
            target_type="manual_review_case",
            target_id=review_case.id,
            after={**review_payload, "status": review_case.status.value},
            occurred_at=now,
        )
        add_outbox_event(
            session,
            store_id=order.store_id,
            aggregate_type="manual_review_case",
            aggregate_id=review_case.id,
            event_type="manual_review.opened",
            payload=review_payload,
            deduplication_key=f"manual-review-opened:{review_case.id}",
            occurred_at=now,
        )
    receipt = await create_sale_receipt(session, order)
    add_audit_log(
        session,
        tenant_id=order.tenant_id,
        store_id=order.store_id,
        actor_type=ActorType.PROVIDER,
        action="order.confirmed",
        target_type="sales_order",
        target_id=order.id,
        actor_device_id=order.kiosk_id,
        after={
            "status": order.status.value,
            "payment_status": order.payment_status.value,
            "ticket_id": str(ticket.id) if ticket is not None else None,
            "receipt_id": str(receipt.id),
            "release_issue": release_issue,
        },
        occurred_at=now,
    )
    add_outbox_event(
        session,
        store_id=order.store_id,
        aggregate_type="sales_order",
        aggregate_id=order.id,
        event_type="order.confirmed",
        payload={
            "order_id": str(order.id),
            "ticket_id": str(ticket.id) if ticket is not None else None,
            "receipt_id": str(receipt.id),
            "version": order.version,
            "release_issue": release_issue,
        },
        deduplication_key=f"order-confirmed:{order.id}",
        occurred_at=now,
    )
    if ticket is not None:
        add_outbox_event(
            session,
            store_id=order.store_id,
            aggregate_type="fulfillment_ticket",
            aggregate_id=ticket.id,
            event_type="fulfillment.ticket.created",
            payload={
                "ticket_id": str(ticket.id),
                "order_id": str(order.id),
                "status": ticket.status.value,
                "release_issue": release_issue,
            },
            deduplication_key=f"ticket-created:{ticket.id}",
            occurred_at=now,
        )
    if release_issue is not None:
        add_audit_log(
            session,
            tenant_id=order.tenant_id,
            store_id=order.store_id,
            actor_type=ActorType.SYSTEM,
            action="fulfillment.release_blocked",
            target_type="sales_order",
            target_id=order.id,
            after={
                "payment_status": order.payment_status.value,
                "release_issue": release_issue,
                "ticket_id": str(ticket.id) if ticket is not None else None,
                "manual_review_case_id": (str(review_case.id) if review_case is not None else None),
            },
            occurred_at=now,
        )
        add_outbox_event(
            session,
            store_id=order.store_id,
            aggregate_type="sales_order",
            aggregate_id=order.id,
            event_type="fulfillment.release_blocked",
            payload={
                "order_id": str(order.id),
                "release_issue": release_issue,
                "ticket_id": str(ticket.id) if ticket is not None else None,
                "manual_review_case_id": (str(review_case.id) if review_case is not None else None),
            },
            deduplication_key=f"fulfillment-release-blocked:{order.id}",
            occurred_at=now,
        )


async def execute_refund(
    database: Database,
    adapter: PaymentAdapter,
    principal: Principal,
    *,
    refund_id: UUID,
    reconcile: bool = False,
) -> RefundResponse:
    if not adapter.available:
        raise DomainError(
            "payment_adapter_unavailable",
            "No approved payment adapter is configured",
            status_code=503,
        )
    async with database.session_factory() as session, session.begin():
        row = (
            await session.execute(
                select(Refund, PaymentAttempt, SalesOrder)
                .join(PaymentAttempt, PaymentAttempt.id == Refund.payment_attempt_id)
                .join(SalesOrder, SalesOrder.id == Refund.order_id)
                .where(Refund.id == refund_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("refund", str(refund_id))
        refund, attempt, order = row
        principal.require_store(order.store_id)
        if attempt.provider != adapter.provider:
            raise DomainError(
                "payment_adapter_mismatch",
                "The configured adapter cannot process this refund",
                status_code=503,
            )
        if refund.status in {RefundStatus.SUCCEEDED, RefundStatus.FAILED}:
            if reconcile:
                raise ConflictError(
                    "refund_not_reconcilable",
                    "Only a refund with an unknown provider result can be reconciled",
                )
            return to_refund_response(refund)
        if reconcile and refund.status != RefundStatus.UNKNOWN:
            raise ConflictError(
                "refund_not_reconcilable",
                "Only a refund with an unknown provider result can be reconciled",
            )
        if not reconcile and refund.status == RefundStatus.UNKNOWN:
            raise ConflictError(
                "refund_result_unknown",
                "The refund result is unknown and must be reconciled",
            )
        remaining_paid_minor = order.paid_minor - order.refunded_minor
        if refund.amount_minor <= 0 or refund.amount_minor > remaining_paid_minor:
            raise ConflictError(
                "invalid_refund_amount",
                "The refund amount is no longer available on the paid order",
            )
        if refund.currency != order.currency or refund.currency != attempt.currency:
            raise ConflictError(
                "refund_currency_mismatch",
                "The refund currency does not match the original payment",
            )
        if attempt.psp_reference is None:
            raise ConflictError(
                "payment_reference_missing",
                "The successful payment has no provider reference for refunding",
            )
        command = RefundCommand(
            refund_id=refund.id,
            provider_service_id=str(refund.id),
            original_psp_reference=attempt.psp_reference,
            amount_minor=refund.amount_minor,
            currency=refund.currency,
        )
        prior_status = refund.status
        prior_version = refund.version
        if not reconcile:
            # Claim the external call before releasing the database lock. If the
            # process stops after this commit, the only safe continuation is a query.
            refund.status = RefundStatus.UNKNOWN
            refund.version += 1
        add_audit_log(
            session,
            tenant_id=order.tenant_id,
            store_id=order.store_id,
            actor_type=ActorType.USER,
            actor_user_id=principal.user_id,
            action=(
                "refund.reconciliation_requested" if reconcile else "refund.execution_requested"
            ),
            target_type="refund",
            target_id=refund.id,
            before={"status": prior_status.value, "version": prior_version},
            after={"status": refund.status.value, "version": refund.version},
            metadata={
                "amount_minor": refund.amount_minor,
                "currency": refund.currency,
                "provider": attempt.provider.value,
                "request_type": "RECONCILE" if reconcile else "EXECUTE",
            },
        )

    try:
        result = await adapter.query_refund(command) if reconcile else await adapter.refund(command)
    except DomainError:
        raise
    except Exception as exc:
        result = RefundResult(
            provider=adapter.provider,
            provider_event_id=f"local-refund-unknown-{uuid4()}",
            status=RefundStatus.UNKNOWN,
            failure_code=type(exc).__name__,
        )
    return await apply_refund_result(database, refund_id=refund_id, result=result)


async def apply_refund_result(
    database: Database,
    *,
    refund_id: UUID,
    result: RefundResult,
) -> RefundResponse:
    if result.status not in {
        RefundStatus.SUCCEEDED,
        RefundStatus.FAILED,
        RefundStatus.UNKNOWN,
    }:
        raise ValueError("A refund result has an unsupported status")
    async with database.session_factory() as session, session.begin():
        review_action = await session.scalar(
            select(ManualReviewAction).where(ManualReviewAction.related_refund_id == refund_id)
        )
        review_case = (
            await session.scalar(
                select(ManualReviewCase)
                .where(ManualReviewCase.id == review_action.case_id)
                .with_for_update()
            )
            if review_action is not None
            else None
        )
        row = (
            await session.execute(
                select(Refund, PaymentAttempt, SalesOrder)
                .join(PaymentAttempt, PaymentAttempt.id == Refund.payment_attempt_id)
                .join(SalesOrder, SalesOrder.id == Refund.order_id)
                .where(Refund.id == refund_id)
                .with_for_update()
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("refund", str(refund_id))
        refund, attempt, order = row
        if attempt.provider != result.provider:
            raise ConflictError(
                "payment_provider_mismatch",
                "The refund provider does not match the original payment",
            )
        provider_event_id = sanitize_provider_identifier(
            result.provider_event_id,
            fallback_scope=f"refund:{refund.id}",
        )
        safe_psp_reference = sanitize_provider_text(result.psp_reference, maximum_length=160)
        safe_failure_code = sanitize_provider_text(result.failure_code, maximum_length=100)
        payload_hash = canonical_json_hash(
            {
                "refund_id": str(refund.id),
                "provider": result.provider.value,
                "provider_event_id": provider_event_id,
                "status": result.status.value,
                "psp_reference": safe_psp_reference,
                "failure_code": safe_failure_code,
            }
        )
        existing_transaction = await session.scalar(
            select(PaymentTransaction).where(
                PaymentTransaction.provider == result.provider,
                PaymentTransaction.provider_event_id == provider_event_id,
            )
        )
        if existing_transaction is not None:
            if (
                existing_transaction.attempt_id != attempt.id
                or existing_transaction.transaction_kind != PaymentTransactionKind.REFUND
                or existing_transaction.amount_minor != refund.amount_minor
                or existing_transaction.currency != refund.currency
                or existing_transaction.payload_hash != payload_hash
            ):
                raise ConflictError(
                    "payment_event_conflict",
                    "The provider event was already recorded for different refund data",
                )
            if refund.status == result.status:
                return to_refund_response(refund)
            raise ConflictError(
                "refund_event_state_conflict",
                "The recorded refund event does not match the current refund state",
            )
        if refund.status in {RefundStatus.SUCCEEDED, RefundStatus.FAILED}:
            if refund.status == result.status:
                return to_refund_response(refund)
            raise ConflictError(
                "refund_terminal_state_conflict",
                "A terminal refund cannot transition to a different provider result",
            )

        now = utc_now()
        refund.status = result.status
        if safe_psp_reference is not None:
            refund.psp_reference = safe_psp_reference
        refund.failure_code = safe_failure_code
        refund.completed_at = (
            now if result.status in {RefundStatus.SUCCEEDED, RefundStatus.FAILED} else None
        )
        refund.version += 1

        if result.status == RefundStatus.SUCCEEDED:
            if order.refunded_minor + refund.amount_minor > order.paid_minor:
                raise ConflictError(
                    "refund_exceeds_paid_amount",
                    "Applying this refund would exceed the paid amount",
                )
            order.refunded_minor += refund.amount_minor
            order.payment_status = (
                PaymentStatus.REFUNDED
                if order.refunded_minor == order.paid_minor
                else PaymentStatus.PARTIALLY_REFUNDED
            )
            attempt.status = order.payment_status
            attempt.version += 1
            order.version += 1
            await create_refund_receipt(session, order, refund)
        elif result.status == RefundStatus.FAILED:
            order.payment_status = (
                PaymentStatus.REFUNDED
                if order.refunded_minor == order.paid_minor
                else (
                    PaymentStatus.PARTIALLY_REFUNDED
                    if order.refunded_minor > 0
                    else PaymentStatus.PAID
                )
            )
            attempt.status = order.payment_status
            attempt.version += 1
            order.version += 1
        else:
            if order.payment_status != PaymentStatus.REFUND_PENDING:
                order.payment_status = PaymentStatus.REFUND_PENDING
                order.version += 1
            if attempt.status != PaymentStatus.REFUND_PENDING:
                attempt.status = PaymentStatus.REFUND_PENDING
                attempt.version += 1

        transaction_status = {
            RefundStatus.SUCCEEDED: order.payment_status,
            RefundStatus.FAILED: PaymentStatus.FAILED,
            RefundStatus.UNKNOWN: PaymentStatus.UNKNOWN,
        }[result.status]
        session.add(
            PaymentTransaction(
                attempt_id=attempt.id,
                provider=result.provider,
                transaction_kind=PaymentTransactionKind.REFUND,
                status=transaction_status,
                amount_minor=refund.amount_minor,
                currency=refund.currency,
                provider_event_id=provider_event_id,
                psp_reference=safe_psp_reference,
                occurred_at=now,
                received_at=now,
                payload_hash=payload_hash,
                payload_redacted={
                    "status": result.status.value,
                    "failure_code": safe_failure_code,
                },
            )
        )

        if review_case is not None:
            if result.status == RefundStatus.SUCCEEDED:
                review_case.status = ReviewStatus.RESOLVED
                review_case.resolved_at = now
            elif result.status == RefundStatus.FAILED:
                review_case.status = ReviewStatus.ASSIGNED
            else:
                review_case.status = ReviewStatus.ACTION_PENDING
            review_case.version += 1

        add_audit_log(
            session,
            tenant_id=order.tenant_id,
            store_id=order.store_id,
            actor_type=ActorType.PROVIDER,
            action="refund.status_changed",
            target_type="refund",
            target_id=refund.id,
            after={
                "status": refund.status.value,
                "amount_minor": refund.amount_minor,
                "order_payment_status": order.payment_status.value,
            },
            occurred_at=now,
        )
        add_outbox_event(
            session,
            store_id=order.store_id,
            aggregate_type="refund",
            aggregate_id=refund.id,
            event_type="refund.status_changed",
            payload={
                "refund_id": str(refund.id),
                "order_id": str(order.id),
                "status": refund.status.value,
            },
            deduplication_key=(
                f"refund-status:{refund.id}:{canonical_json_hash(provider_event_id)}"
            ),
            occurred_at=now,
        )
        await session.flush()
        if result.status == RefundStatus.SUCCEEDED:
            await close_order_if_complete(session, order, actor_user_id=None)
        return to_refund_response(refund)


async def list_refunds_for_stores(
    session: AsyncSession,
    store_ids: frozenset[UUID],
    *,
    limit: int,
) -> list[RefundResponse]:
    if not store_ids:
        return []
    refunds = list(
        (
            await session.scalars(
                select(Refund)
                .join(SalesOrder, SalesOrder.id == Refund.order_id)
                .where(SalesOrder.store_id.in_(store_ids))
                .order_by(Refund.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [to_refund_response(refund) for refund in refunds]


def to_refund_response(refund: Refund) -> RefundResponse:
    return RefundResponse(
        id=refund.id,
        order_id=refund.order_id,
        payment_attempt_id=refund.payment_attempt_id,
        amount_minor=refund.amount_minor,
        currency=refund.currency,
        reason_code=refund.reason_code,
        status=refund.status,
        psp_reference=refund.psp_reference,
        failure_code=refund.failure_code,
        completed_at=refund.completed_at,
        version=refund.version,
    )


async def count_paid_orders_without_tickets(session: AsyncSession) -> int:
    count = await session.scalar(
        select(func.count(SalesOrder.id))
        .outerjoin(FulfillmentTicket, FulfillmentTicket.order_id == SalesOrder.id)
        .where(SalesOrder.payment_status == PaymentStatus.PAID, FulfillmentTicket.id.is_(None))
    )
    return int(count or 0)
