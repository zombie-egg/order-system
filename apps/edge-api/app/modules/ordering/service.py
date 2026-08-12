from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import (
    ActorType,
    FulfillmentEndpointType,
    FulfillmentStatus,
    IdempotencyStatus,
    OrderStatus,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    QuoteStatus,
)
from app.core.errors import ConflictError, NotFoundError
from app.modules.audit.service import (
    acquire_idempotency_record,
    add_audit_log,
    add_outbox_event,
    complete_idempotency_record,
)
from app.modules.kitchen_fulfillment.models import FulfillmentTicket
from app.modules.ordering.models import (
    OrderDiscountLine,
    OrderItem,
    OrderItemOption,
    OrderStatusEvent,
    OrderTaxLine,
    SalesOrder,
    StoreNumberSequence,
)
from app.modules.ordering.schemas import (
    OrderItemResponse,
    OrderOptionResponse,
    OrderResponse,
    PaymentAttemptResponse,
)
from app.modules.organization.models import (
    FulfillmentEndpoint,
    KitchenStation,
    LegalEntity,
    PaymentTerminal,
    Store,
    StoreOperatingPolicy,
)
from app.modules.payments.models import PaymentAttempt
from app.modules.pricing_tax.models import (
    PriceQuote,
    PriceQuoteDiscountLine,
    PriceQuoteItem,
    PriceQuoteItemOption,
    PriceQuoteTaxLine,
)
from app.persistence.base import utc_now

TERMINAL_FULFILLMENT_STATUSES = {
    FulfillmentStatus.COLLECTED,
    FulfillmentStatus.UNFULFILLABLE,
    FulfillmentStatus.CANCELLED,
}


def _business_date(store: Store) -> date:
    try:
        timezone = ZoneInfo(store.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConflictError(
            "invalid_store_timezone",
            "The store timezone is not available on this Windows installation",
        ) from exc
    return utc_now().astimezone(timezone).date()


async def _ensure_fulfillment_available(
    session: AsyncSession,
    store: Store,
    policy: StoreOperatingPolicy,
) -> KitchenStation:
    stations = list(
        (
            await session.scalars(
                select(KitchenStation).where(
                    KitchenStation.store_id == store.id,
                    KitchenStation.active,
                    KitchenStation.is_default,
                )
            )
        ).all()
    )
    if not stations:
        raise ConflictError(
            "fulfillment_station_unavailable",
            "No active default manual fulfillment station is configured",
        )
    if len(stations) != 1:
        raise ConflictError(
            "fulfillment_station_ambiguous",
            "Exactly one active default manual fulfillment station must be configured",
        )
    station = stations[0]
    heartbeat_cutoff = utc_now() - timedelta(seconds=policy.kds_heartbeat_seconds)
    endpoints = list(
        (
            await session.scalars(
                select(FulfillmentEndpoint).where(
                    FulfillmentEndpoint.station_id == station.id,
                    FulfillmentEndpoint.active,
                    FulfillmentEndpoint.last_heartbeat_at.is_not(None),
                    FulfillmentEndpoint.last_heartbeat_at >= heartbeat_cutoff,
                )
            )
        ).all()
    )
    kds_online = any(
        endpoint.endpoint_type == FulfillmentEndpointType.KDS for endpoint in endpoints
    )
    printer_online = any(
        endpoint.endpoint_type == FulfillmentEndpointType.PRINTER for endpoint in endpoints
    )
    if not kds_online and not (policy.printer_fallback_enabled and printer_online):
        raise ConflictError(
            "fulfillment_path_unavailable",
            "No live KDS or approved printer fallback is available; payment is paused",
        )
    open_count = await session.scalar(
        select(func.count(FulfillmentTicket.id)).where(
            FulfillmentTicket.station_id == station.id,
            FulfillmentTicket.status.not_in(TERMINAL_FULFILLMENT_STATUSES),
        )
    )
    if int(open_count or 0) >= policy.max_open_tickets:
        raise ConflictError(
            "fulfillment_queue_full",
            "The manual fulfillment queue has reached its configured limit",
        )
    return station


async def _allocate_sequence(
    session: AsyncSession,
    *,
    store_id: UUID,
    business_date: date,
) -> int:
    increment = (
        update(StoreNumberSequence)
        .where(
            StoreNumberSequence.store_id == store_id,
            StoreNumberSequence.business_date == business_date,
            StoreNumberSequence.sequence_kind == "ORDER",
        )
        .values(next_value=StoreNumberSequence.next_value + 1)
        .returning(StoreNumberSequence.next_value)
    )
    incremented_value = await session.scalar(increment)
    if incremented_value is not None:
        return int(incremented_value) - 1

    try:
        async with session.begin_nested():
            session.add(
                StoreNumberSequence(
                    store_id=store_id,
                    business_date=business_date,
                    sequence_kind="ORDER",
                    next_value=2,
                )
            )
            await session.flush()
        return 1
    except IntegrityError:
        incremented_value = await session.scalar(increment)
        if incremented_value is None:
            raise RuntimeError("The store number sequence could not be allocated") from None
        return int(incremented_value) - 1


async def _validate_quote_snapshot(session: AsyncSession, quote: PriceQuote) -> None:
    item_totals = (
        await session.execute(
            select(
                func.count(PriceQuoteItem.id),
                func.coalesce(
                    func.sum(
                        (PriceQuoteItem.unit_price_minor + PriceQuoteItem.option_total_minor)
                        * PriceQuoteItem.quantity
                    ),
                    0,
                ),
                func.coalesce(func.sum(PriceQuoteItem.discount_minor), 0),
                func.coalesce(func.sum(PriceQuoteItem.net_minor), 0),
                func.coalesce(func.sum(PriceQuoteItem.tax_minor), 0),
                func.coalesce(func.sum(PriceQuoteItem.line_total_minor), 0),
            ).where(PriceQuoteItem.quote_id == quote.id)
        )
    ).one()
    item_count, subtotal, discount, net, tax, total = (int(value or 0) for value in item_totals)
    tax_totals = (
        await session.execute(
            select(
                func.coalesce(func.sum(PriceQuoteTaxLine.taxable_minor), 0),
                func.coalesce(func.sum(PriceQuoteTaxLine.tax_minor), 0),
            ).where(PriceQuoteTaxLine.quote_id == quote.id)
        )
    ).one()
    taxable_total, tax_line_total = (int(value or 0) for value in tax_totals)
    option_totals = (
        select(
            PriceQuoteItemOption.quote_item_id.label("quote_item_id"),
            func.sum(PriceQuoteItemOption.price_delta_minor).label("option_total_minor"),
        )
        .group_by(PriceQuoteItemOption.quote_item_id)
        .subquery()
    )
    mismatched_option_count = await session.scalar(
        select(func.count(PriceQuoteItem.id))
        .outerjoin(
            option_totals,
            option_totals.c.quote_item_id == PriceQuoteItem.id,
        )
        .where(
            PriceQuoteItem.quote_id == quote.id,
            func.coalesce(option_totals.c.option_total_minor, 0)
            != PriceQuoteItem.option_total_minor,
        )
    )
    mismatched_price_policy_count = await session.scalar(
        select(func.count(PriceQuoteItem.id)).where(
            PriceQuoteItem.quote_id == quote.id,
            PriceQuoteItem.prices_include_tax != quote.prices_include_tax,
        )
    )
    item_tax_breakdown = {
        (tax_category_code, int(tax_rate_ppm)): (int(net_minor), int(tax_minor))
        for tax_category_code, tax_rate_ppm, net_minor, tax_minor in (
            await session.execute(
                select(
                    PriceQuoteItem.tax_category_code,
                    PriceQuoteItem.tax_rate_ppm,
                    func.sum(PriceQuoteItem.net_minor),
                    func.sum(PriceQuoteItem.tax_minor),
                )
                .where(PriceQuoteItem.quote_id == quote.id)
                .group_by(PriceQuoteItem.tax_category_code, PriceQuoteItem.tax_rate_ppm)
            )
        ).all()
    }
    tax_line_breakdown = {
        (line.tax_category_code, line.tax_rate_ppm): (line.taxable_minor, line.tax_minor)
        for line in (
            await session.scalars(
                select(PriceQuoteTaxLine).where(PriceQuoteTaxLine.quote_id == quote.id)
            )
        ).all()
    }
    discount_line_total = await session.scalar(
        select(func.coalesce(func.sum(PriceQuoteDiscountLine.amount_minor), 0)).where(
            PriceQuoteDiscountLine.quote_id == quote.id
        )
    )
    invalid_discount_item_count = await session.scalar(
        select(func.count(PriceQuoteDiscountLine.id))
        .outerjoin(
            PriceQuoteItem,
            (PriceQuoteItem.id == PriceQuoteDiscountLine.quote_item_id)
            & (PriceQuoteItem.quote_id == quote.id),
        )
        .where(
            PriceQuoteDiscountLine.quote_id == quote.id,
            PriceQuoteDiscountLine.quote_item_id.is_not(None),
            PriceQuoteItem.id.is_(None),
        )
    )
    if (
        item_count == 0
        or (
            subtotal,
            discount,
            net,
            tax,
            total,
            taxable_total,
            tax_line_total,
        )
        != (
            quote.subtotal_minor,
            quote.discount_minor,
            quote.net_minor,
            quote.tax_minor,
            quote.total_minor,
            quote.net_minor,
            quote.tax_minor,
        )
        or any(
            (
                int(mismatched_option_count or 0) > 0,
                int(mismatched_price_policy_count or 0) > 0,
                item_tax_breakdown != tax_line_breakdown,
                int(discount_line_total or 0) != quote.discount_minor,
                int(invalid_discount_item_count or 0) > 0,
                quote.schema_version != 1,
                quote.snapshot.get("schema_version") != 1,
            )
        )
    ):
        raise ConflictError(
            "quote_snapshot_invalid",
            "The immutable quote snapshot does not reconcile and cannot be ordered",
        )


async def create_order(
    session: AsyncSession,
    settings: Settings,
    *,
    kiosk_id: UUID,
    store_id: UUID,
    quote_id: UUID,
    payment_method: PaymentMethod,
    idempotency_key: str,
) -> OrderResponse:
    record, created = await acquire_idempotency_record(
        session,
        namespace="create_order",
        actor_scope=str(kiosk_id),
        idempotency_key=idempotency_key,
        request_payload={"quote_id": str(quote_id), "payment_method": payment_method.value},
    )
    if not created:
        if record.status == IdempotencyStatus.COMPLETED and record.resource_id is not None:
            return await get_order_for_kiosk(session, kiosk_id, record.resource_id)
        raise ConflictError(
            "idempotency_request_in_progress",
            "A request with this Idempotency-Key is still being processed",
        )

    quote = await session.scalar(
        select(PriceQuote).where(PriceQuote.id == quote_id).with_for_update()
    )
    if quote is None or quote.store_id != store_id or quote.kiosk_id != kiosk_id:
        raise NotFoundError("price_quote", str(quote_id))
    now = utc_now()
    if quote.status != QuoteStatus.ACTIVE:
        raise ConflictError("quote_not_active", "The quote is no longer active")
    if quote.expires_at <= now:
        raise ConflictError("quote_expired", "The quote has expired and must be recalculated")
    if quote.total_minor <= 0:
        raise ConflictError(
            "quote_not_payable",
            "The quote total must be positive before starting a payment",
        )
    await _validate_quote_snapshot(session, quote)

    store_row = (
        await session.execute(
            select(Store, LegalEntity, StoreOperatingPolicy)
            .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
            .join(StoreOperatingPolicy, StoreOperatingPolicy.store_id == Store.id)
            .where(Store.id == store_id, Store.active, LegalEntity.active)
        )
    ).one_or_none()
    if store_row is None:
        raise NotFoundError("store", str(store_id))
    store, legal_entity, policy = store_row
    if quote.currency != store.currency:
        raise ConflictError(
            "quote_currency_mismatch",
            "The quote currency no longer matches the store currency",
        )
    if not policy.accepting_orders:
        raise ConflictError("store_not_accepting_orders", "The store is not accepting orders")
    await _ensure_fulfillment_available(session, store, policy)

    terminal = await session.scalar(
        select(PaymentTerminal).where(
            PaymentTerminal.kiosk_id == kiosk_id,
            PaymentTerminal.active,
        )
    )
    if terminal is None:
        raise ConflictError(
            "payment_terminal_unavailable",
            "No active payment terminal is bound to this kiosk",
        )
    if terminal.provider == PaymentProvider.MOCK and not settings.mock_payment_enabled:
        raise ConflictError(
            "mock_payment_disabled",
            "The development payment adapter is disabled",
        )

    business_date = _business_date(store)
    sequence_number = await _allocate_sequence(
        session,
        store_id=store.id,
        business_date=business_date,
    )
    order_number = f"{store.code}-{business_date:%Y%m%d}-{sequence_number:06d}"
    if len(order_number) > 80:
        raise ConflictError(
            "order_number_too_long",
            "The store code cannot produce a valid commercial order number",
        )
    order = SalesOrder(
        tenant_id=legal_entity.tenant_id,
        store_id=store.id,
        kiosk_id=kiosk_id,
        quote_id=quote.id,
        business_date=business_date,
        sequence_number=sequence_number,
        order_number=order_number,
        display_number=f"{sequence_number:03d}",
        status=OrderStatus.DRAFT,
        payment_status=PaymentStatus.INITIATED,
        currency=quote.currency,
        locale=quote.locale,
        prices_include_tax=quote.prices_include_tax,
        subtotal_minor=quote.subtotal_minor,
        discount_minor=quote.discount_minor,
        net_minor=quote.net_minor,
        tax_minor=quote.tax_minor,
        total_minor=quote.total_minor,
    )
    session.add(order)
    await session.flush()

    quote_items = list(
        (
            await session.scalars(
                select(PriceQuoteItem)
                .where(PriceQuoteItem.quote_id == quote.id)
                .order_by(PriceQuoteItem.line_number)
            )
        ).all()
    )
    quote_item_ids = [item.id for item in quote_items]
    quote_options = list(
        (
            await session.scalars(
                select(PriceQuoteItemOption)
                .where(PriceQuoteItemOption.quote_item_id.in_(quote_item_ids))
                .order_by(
                    PriceQuoteItemOption.quote_item_id,
                    PriceQuoteItemOption.option_number,
                )
            )
        ).all()
    )
    options_by_quote_item: dict[UUID, list[PriceQuoteItemOption]] = defaultdict(list)
    for option in quote_options:
        options_by_quote_item[option.quote_item_id].append(option)

    order_item_by_quote_item: dict[UUID, OrderItem] = {}
    for quote_item in quote_items:
        order_item = OrderItem(
            order_id=order.id,
            line_number=quote_item.line_number,
            product_id=quote_item.product_id,
            sku_snapshot=quote_item.sku_snapshot,
            name_snapshot=quote_item.name_snapshot,
            quantity=quote_item.quantity,
            prices_include_tax=quote_item.prices_include_tax,
            unit_price_minor=quote_item.unit_price_minor,
            option_total_minor=quote_item.option_total_minor,
            discount_minor=quote_item.discount_minor,
            tax_category_code=quote_item.tax_category_code,
            tax_rate_ppm=quote_item.tax_rate_ppm,
            net_minor=quote_item.net_minor,
            tax_minor=quote_item.tax_minor,
            line_total_minor=quote_item.line_total_minor,
            preparation_snapshot=quote_item.preparation_snapshot,
            allergen_snapshot=quote_item.allergen_snapshot,
        )
        session.add(order_item)
        await session.flush()
        order_item_by_quote_item[quote_item.id] = order_item
        session.add_all(
            OrderItemOption(
                order_item_id=order_item.id,
                option_number=option.option_number,
                option_group_id=option.option_group_id,
                option_value_id=option.option_value_id,
                group_code_snapshot=option.group_code_snapshot,
                group_name_snapshot=option.group_name_snapshot,
                value_code_snapshot=option.value_code_snapshot,
                name_snapshot=option.name_snapshot,
                price_delta_minor=option.price_delta_minor,
            )
            for option in options_by_quote_item[quote_item.id]
        )

    tax_lines = list(
        (
            await session.scalars(
                select(PriceQuoteTaxLine).where(PriceQuoteTaxLine.quote_id == quote.id)
            )
        ).all()
    )
    session.add_all(
        OrderTaxLine(
            order_id=order.id,
            tax_category_code=line.tax_category_code,
            tax_rate_ppm=line.tax_rate_ppm,
            taxable_minor=line.taxable_minor,
            tax_minor=line.tax_minor,
        )
        for line in tax_lines
    )
    discount_lines = list(
        (
            await session.scalars(
                select(PriceQuoteDiscountLine).where(PriceQuoteDiscountLine.quote_id == quote.id)
            )
        ).all()
    )
    session.add_all(
        OrderDiscountLine(
            order_id=order.id,
            order_item_id=(
                order_item_by_quote_item[line.quote_item_id].id
                if line.quote_item_id is not None
                else None
            ),
            promotion_id=line.promotion_id,
            code_snapshot=line.code_snapshot,
            amount_minor=line.amount_minor,
        )
        for line in discount_lines
    )
    attempt = PaymentAttempt(
        order_id=order.id,
        attempt_number=1,
        provider=terminal.provider,
        payment_method=payment_method,
        terminal_id=terminal.id,
        status=PaymentStatus.INITIATED,
        amount_minor=order.total_minor,
        currency=order.currency,
        merchant_reference=order.order_number,
        provider_service_id=str(uuid4()),
        requested_at=now,
    )
    session.add(attempt)
    session.add(
        OrderStatusEvent(
            order_id=order.id,
            sequence_number=1,
            from_status=None,
            to_status=OrderStatus.DRAFT,
            actor_type=ActorType.KIOSK,
            actor_device_id=kiosk_id,
            occurred_at=now,
        )
    )
    quote.status = QuoteStatus.CONSUMED
    quote.consumed_at = now
    await session.flush()
    add_audit_log(
        session,
        tenant_id=order.tenant_id,
        store_id=order.store_id,
        actor_type=ActorType.KIOSK,
        actor_device_id=kiosk_id,
        action="order.created",
        target_type="sales_order",
        target_id=order.id,
        after={
            "status": order.status.value,
            "payment_status": order.payment_status.value,
            "payment_attempt_id": str(attempt.id),
            "total_minor": order.total_minor,
            "currency": order.currency,
        },
        occurred_at=now,
    )
    add_outbox_event(
        session,
        store_id=order.store_id,
        aggregate_type="sales_order",
        aggregate_id=order.id,
        event_type="order.created",
        payload={
            "order_id": str(order.id),
            "payment_attempt_id": str(attempt.id),
            "status": order.status.value,
            "version": order.version,
        },
        deduplication_key=f"order-created:{order.id}",
        occurred_at=now,
    )

    response = await get_order_for_kiosk(session, kiosk_id, order.id)
    complete_idempotency_record(
        record,
        resource_type="sales_order",
        resource_id=order.id,
        response_status=201,
        response_json={"order_id": str(order.id), "payment_attempt_id": str(attempt.id)},
    )
    return response


async def create_retry_payment_attempt(
    session: AsyncSession,
    settings: Settings,
    *,
    kiosk_id: UUID,
    store_id: UUID,
    order_id: UUID,
    payment_method: PaymentMethod,
    idempotency_key: str,
) -> OrderResponse:
    record, created = await acquire_idempotency_record(
        session,
        namespace="retry_payment",
        actor_scope=str(kiosk_id),
        idempotency_key=idempotency_key,
        request_payload={
            "order_id": str(order_id),
            "payment_method": payment_method.value,
        },
    )
    if not created:
        if record.status == IdempotencyStatus.COMPLETED and record.resource_id is not None:
            return await get_order_for_kiosk(session, kiosk_id, record.resource_id)
        raise ConflictError(
            "idempotency_request_in_progress",
            "A request with this Idempotency-Key is still being processed",
        )

    order = await session.scalar(
        select(SalesOrder)
        .where(
            SalesOrder.id == order_id,
            SalesOrder.kiosk_id == kiosk_id,
            SalesOrder.store_id == store_id,
        )
        .with_for_update()
    )
    if order is None:
        raise NotFoundError("sales_order", str(order_id))
    if order.status != OrderStatus.DRAFT or order.payment_status != PaymentStatus.FAILED:
        raise ConflictError(
            "payment_retry_not_allowed",
            "Only a draft order with a confirmed failed payment can be retried",
        )
    store_row = (
        await session.execute(
            select(Store, StoreOperatingPolicy)
            .join(StoreOperatingPolicy, StoreOperatingPolicy.store_id == Store.id)
            .where(Store.id == store_id, Store.active)
        )
    ).one_or_none()
    if store_row is None:
        raise NotFoundError("store", str(store_id))
    store, policy = store_row
    if not policy.accepting_orders:
        raise ConflictError("store_not_accepting_orders", "The store is not accepting orders")
    await _ensure_fulfillment_available(session, store, policy)

    terminal = await session.scalar(
        select(PaymentTerminal).where(
            PaymentTerminal.kiosk_id == kiosk_id,
            PaymentTerminal.active,
        )
    )
    if terminal is None:
        raise ConflictError(
            "payment_terminal_unavailable",
            "No active payment terminal is bound to this kiosk",
        )
    if terminal.provider == PaymentProvider.MOCK and not settings.mock_payment_enabled:
        raise ConflictError(
            "mock_payment_disabled",
            "The development payment adapter is disabled",
        )

    latest_attempt_number = await session.scalar(
        select(func.coalesce(func.max(PaymentAttempt.attempt_number), 0)).where(
            PaymentAttempt.order_id == order.id
        )
    )
    attempt_number = int(latest_attempt_number or 0) + 1
    now = utc_now()
    attempt = PaymentAttempt(
        order_id=order.id,
        attempt_number=attempt_number,
        provider=terminal.provider,
        payment_method=payment_method,
        terminal_id=terminal.id,
        status=PaymentStatus.INITIATED,
        amount_minor=order.total_minor,
        currency=order.currency,
        merchant_reference=f"{order.order_number}-A{attempt_number}",
        provider_service_id=str(uuid4()),
        requested_at=now,
    )
    session.add(attempt)
    order.payment_status = PaymentStatus.INITIATED
    order.version += 1
    await session.flush()
    add_audit_log(
        session,
        tenant_id=order.tenant_id,
        store_id=order.store_id,
        actor_type=ActorType.KIOSK,
        actor_device_id=kiosk_id,
        action="payment.retry_created",
        target_type="payment_attempt",
        target_id=attempt.id,
        after={
            "order_id": str(order.id),
            "attempt_number": attempt.attempt_number,
            "status": attempt.status.value,
            "amount_minor": attempt.amount_minor,
            "currency": attempt.currency,
        },
        occurred_at=now,
    )
    add_outbox_event(
        session,
        store_id=order.store_id,
        aggregate_type="payment_attempt",
        aggregate_id=attempt.id,
        event_type="payment.attempt.created",
        payload={
            "attempt_id": str(attempt.id),
            "order_id": str(order.id),
            "attempt_number": attempt.attempt_number,
        },
        deduplication_key=f"payment-attempt-created:{attempt.id}",
        occurred_at=now,
    )
    complete_idempotency_record(
        record,
        resource_type="sales_order",
        resource_id=order.id,
        response_status=201,
        response_json={"order_id": str(order.id), "payment_attempt_id": str(attempt.id)},
    )
    return await build_order_response(session, order)


async def get_order_for_kiosk(
    session: AsyncSession,
    kiosk_id: UUID,
    order_id: UUID,
) -> OrderResponse:
    order = await session.scalar(
        select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.kiosk_id == kiosk_id)
    )
    if order is None:
        raise NotFoundError("sales_order", str(order_id))
    return await build_order_response(session, order)


async def get_order_for_store(
    session: AsyncSession,
    store_ids: frozenset[UUID],
    order_id: UUID,
) -> OrderResponse:
    order = await session.scalar(
        select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.store_id.in_(store_ids))
    )
    if order is None:
        raise NotFoundError("sales_order", str(order_id))
    return await build_order_response(session, order)


async def list_orders_for_stores(
    session: AsyncSession,
    store_ids: frozenset[UUID],
    *,
    limit: int,
) -> list[OrderResponse]:
    if not store_ids:
        return []
    orders = list(
        (
            await session.scalars(
                select(SalesOrder)
                .where(SalesOrder.store_id.in_(store_ids))
                .order_by(SalesOrder.created_at.desc())
                .limit(limit)
            )
        ).all()
    )
    return [await build_order_response(session, order) for order in orders]


async def build_order_response(session: AsyncSession, order: SalesOrder) -> OrderResponse:
    items = list(
        (
            await session.scalars(
                select(OrderItem)
                .where(OrderItem.order_id == order.id)
                .order_by(OrderItem.line_number)
            )
        ).all()
    )
    item_ids = [item.id for item in items]
    options = list(
        (
            await session.scalars(
                select(OrderItemOption)
                .where(OrderItemOption.order_item_id.in_(item_ids))
                .order_by(OrderItemOption.order_item_id, OrderItemOption.option_number)
            )
        ).all()
    )
    options_by_item: dict[UUID, list[OrderItemOption]] = defaultdict(list)
    for option in options:
        options_by_item[option.order_item_id].append(option)
    attempts = list(
        (
            await session.scalars(
                select(PaymentAttempt)
                .where(PaymentAttempt.order_id == order.id)
                .order_by(PaymentAttempt.attempt_number)
            )
        ).all()
    )
    return OrderResponse(
        id=order.id,
        store_id=order.store_id,
        kiosk_id=order.kiosk_id,
        quote_id=order.quote_id,
        business_date=order.business_date,
        order_number=order.order_number,
        display_number=order.display_number,
        status=order.status,
        payment_status=order.payment_status,
        currency=order.currency,
        locale=order.locale,
        prices_include_tax=order.prices_include_tax,
        subtotal_minor=order.subtotal_minor,
        discount_minor=order.discount_minor,
        net_minor=order.net_minor,
        tax_minor=order.tax_minor,
        total_minor=order.total_minor,
        paid_minor=order.paid_minor,
        refunded_minor=order.refunded_minor,
        confirmed_at=order.confirmed_at,
        closed_at=order.closed_at,
        version=order.version,
        items=[
            OrderItemResponse(
                id=item.id,
                line_number=item.line_number,
                product_id=item.product_id,
                sku=item.sku_snapshot,
                name=item.name_snapshot,
                quantity=item.quantity,
                unit_price_minor=item.unit_price_minor,
                option_total_minor=item.option_total_minor,
                discount_minor=item.discount_minor,
                net_minor=item.net_minor,
                tax_minor=item.tax_minor,
                line_total_minor=item.line_total_minor,
                allergen_snapshot=item.allergen_snapshot,
                options=[
                    OrderOptionResponse(
                        option_value_id=option.option_value_id,
                        group_name=option.group_name_snapshot,
                        name=option.name_snapshot,
                        price_delta_minor=option.price_delta_minor,
                    )
                    for option in options_by_item[item.id]
                ],
            )
            for item in items
        ],
        payment_attempts=[
            PaymentAttemptResponse(
                id=attempt.id,
                attempt_number=attempt.attempt_number,
                provider=attempt.provider,
                payment_method=attempt.payment_method,
                status=attempt.status,
                amount_minor=attempt.amount_minor,
                currency=attempt.currency,
                psp_reference=attempt.psp_reference,
                failure_code=attempt.failure_code,
                requested_at=attempt.requested_at,
                completed_at=attempt.completed_at,
                version=attempt.version,
            )
            for attempt in attempts
        ],
    )
