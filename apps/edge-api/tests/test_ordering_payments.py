from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

import app.persistence.models  # noqa: F401
from app.core.config import Settings
from app.core.enums import (
    ActorType,
    FulfillmentEndpointType,
    FulfillmentFailureReason,
    FulfillmentStatus,
    MockPaymentScenario,
    OrderStatus,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    PaymentTransactionKind,
    PriceBookStatus,
    QuoteStatus,
    ReceiptType,
    RefundStatus,
    ReviewResolution,
    ReviewStatus,
)
from app.core.errors import ConflictError
from app.core.principals import FulfillmentEndpointPrincipal, Principal
from app.modules.audit.models import AuditLog, IdempotencyRecord, OutboxEvent
from app.modules.audit.service import canonical_json_hash
from app.modules.catalog.models import Category, PriceBook, Product
from app.modules.identity.models import UserAccount
from app.modules.kitchen_fulfillment.models import (
    FulfillmentEvent,
    FulfillmentTicket,
    FulfillmentTicketItem,
)
from app.modules.kitchen_fulfillment.schemas import TransitionTicketRequest
from app.modules.kitchen_fulfillment.service import (
    heartbeat_endpoint,
    list_station_queue,
    transition_ticket,
)
from app.modules.manual_review.models import ManualReviewCase
from app.modules.manual_review.schemas import ResolveReviewRequest
from app.modules.manual_review.service import resolve_review
from app.modules.ordering.models import (
    OrderItem,
    OrderStatusEvent,
    OrderTaxLine,
    SalesOrder,
)
from app.modules.ordering.service import create_order, create_retry_payment_attempt
from app.modules.organization.models import (
    FulfillmentEndpoint,
    KioskDevice,
    KitchenStation,
    LegalEntity,
    PaymentTerminal,
    Store,
    StoreOperatingPolicy,
    Tenant,
)
from app.modules.payments import service as payment_service
from app.modules.payments.models import PaymentAttempt, PaymentTransaction, Refund
from app.modules.payments.providers import (
    AuthorizationResult,
    AuthorizeCommand,
    MockPaymentAdapter,
    RefundCommand,
    RefundResult,
)
from app.modules.pricing_tax.models import (
    PriceQuote,
    PriceQuoteItem,
    PriceQuoteTaxLine,
    TaxPolicyVersion,
)
from app.modules.receipts.models import Receipt
from app.modules.receipts.service import to_receipt_response
from app.persistence.base import Base, utc_now
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class SeedData:
    tenant_id: UUID
    store_id: UUID
    kiosk_id: UUID
    station_id: UUID
    endpoint_id: UUID
    terminal_id: UUID
    user_id: UUID
    quote_id: UUID
    order_id: UUID | None
    attempt_id: UUID | None


class CountingMockPaymentAdapter(MockPaymentAdapter):
    def __init__(self, scenario: MockPaymentScenario) -> None:
        super().__init__(scenario)
        self.authorize_calls = 0

    async def authorize(self, command: AuthorizeCommand) -> AuthorizationResult:
        self.authorize_calls += 1
        return await super().authorize(command)


class ObservingRefundAdapter(MockPaymentAdapter):
    def __init__(self, database: Database) -> None:
        super().__init__(MockPaymentScenario.APPROVED)
        self.database = database
        self.status_during_provider_call: RefundStatus | None = None
        self.request_audit_visible_during_provider_call = False
        self.request_audit_action: str | None = None
        self.request_audit_actor_user_id: UUID | None = None

    async def _observe_request_audit(self, command: RefundCommand, action: str) -> None:
        async with self.database.session_factory() as session:
            audit = await session.scalar(
                select(AuditLog)
                .where(
                    AuditLog.target_type == "refund",
                    AuditLog.target_id == command.refund_id,
                    AuditLog.action == action,
                )
                .order_by(AuditLog.occurred_at.desc())
            )
            assert audit is not None
            self.request_audit_visible_during_provider_call = True
            self.request_audit_action = audit.action
            self.request_audit_actor_user_id = audit.actor_user_id

    async def refund(self, command: RefundCommand) -> RefundResult:
        async with self.database.session_factory() as session:
            refund = await session.get(Refund, command.refund_id)
            assert refund is not None
            self.status_during_provider_call = refund.status
        await self._observe_request_audit(command, "refund.execution_requested")
        return await super().refund(command)

    async def query_refund(self, command: RefundCommand) -> RefundResult:
        await self._observe_request_audit(command, "refund.reconciliation_requested")
        return await super().query_refund(command)


async def _create_database(url: str = "sqlite+aiosqlite:///:memory:") -> Database:
    database = Database(url)
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return database


async def _seed_store(
    database: Database,
    *,
    include_order: bool,
    quote_total_minor: int = 1000,
) -> SeedData:
    tenant_id = uuid4()
    legal_entity_id = uuid4()
    store_id = uuid4()
    kiosk_id = uuid4()
    station_id = uuid4()
    endpoint_id = uuid4()
    terminal_id = uuid4()
    user_id = uuid4()
    category_id = uuid4()
    product_id = uuid4()
    price_book_id = uuid4()
    tax_policy_id = uuid4()
    quote_id = uuid4()
    quote_item_id = uuid4()
    order_id = uuid4() if include_order else None
    attempt_id = uuid4() if include_order else None
    now = utc_now()
    tax_minor = 83 if quote_total_minor == 1000 else 0
    net_minor = quote_total_minor - tax_minor

    tenant = Tenant(id=tenant_id, code="tenant", name="Test Tenant")
    legal_entity = LegalEntity(
        id=legal_entity_id,
        tenant_id=tenant_id,
        code="entity",
        name="Test Entity",
        country_code="NL",
        vat_number="NL000000000B00",
    )
    store = Store(
        id=store_id,
        legal_entity_id=legal_entity_id,
        code="AMS-01",
        name="Amsterdam Test Store",
        country_code="NL",
        currency="EUR",
        locale="nl-NL",
        timezone="Europe/Amsterdam",
    )
    policy = StoreOperatingPolicy(
        store_id=store_id,
        accepting_orders=True,
        max_open_tickets=50,
        kds_heartbeat_seconds=120,
        printer_fallback_enabled=False,
    )
    kiosk = KioskDevice(
        id=kiosk_id,
        store_id=store_id,
        code="KIOSK-01",
        display_name="Kiosk 1",
        credential_hash="k" * 64,
    )
    station = KitchenStation(
        id=station_id,
        store_id=store_id,
        code="BAR-01",
        name="Bar",
        is_default=True,
    )
    endpoint = FulfillmentEndpoint(
        id=endpoint_id,
        station_id=station_id,
        endpoint_type=FulfillmentEndpointType.KDS,
        external_reference="KDS-01",
        credential_hash="e" * 64,
        last_heartbeat_at=now,
    )
    terminal = PaymentTerminal(
        id=terminal_id,
        kiosk_id=kiosk_id,
        provider=PaymentProvider.MOCK,
        terminal_reference="MOCK-TERM-01",
    )
    user = UserAccount(
        id=user_id,
        tenant_id=tenant_id,
        username="operator",
        username_normalized="operator",
        display_name="Operator",
        password_hash="not-used-in-this-test",
    )
    category = Category(id=category_id, tenant_id=tenant_id, code="drinks")
    product = Product(
        id=product_id,
        tenant_id=tenant_id,
        category_id=category_id,
        sku="COFFEE-01",
        tax_category_code="BEVERAGE",
        preparation_data={"recipe": "espresso"},
        allergen_data={"contains": []},
    )
    price_book = PriceBook(
        id=price_book_id,
        tenant_id=tenant_id,
        code="default",
        version=1,
        currency="EUR",
        prices_include_tax=True,
        status=PriceBookStatus.PUBLISHED,
    )
    tax_policy = TaxPolicyVersion(
        id=tax_policy_id,
        tenant_id=tenant_id,
        country_code="NL",
        version=1,
        valid_from=now - timedelta(days=1),
        published=True,
    )
    quote = PriceQuote(
        id=quote_id,
        store_id=store_id,
        kiosk_id=kiosk_id,
        price_book_id=price_book_id,
        tax_policy_version_id=tax_policy_id,
        status=QuoteStatus.CONSUMED if include_order else QuoteStatus.ACTIVE,
        request_hash="q" * 64,
        currency="EUR",
        locale="nl-NL",
        prices_include_tax=True,
        subtotal_minor=quote_total_minor,
        discount_minor=0,
        net_minor=net_minor,
        tax_minor=tax_minor,
        total_minor=quote_total_minor,
        snapshot={"schema_version": 1},
        expires_at=now + timedelta(minutes=15),
        consumed_at=now if include_order else None,
    )
    quote_item = PriceQuoteItem(
        id=quote_item_id,
        quote_id=quote_id,
        line_number=1,
        product_id=product_id,
        sku_snapshot="COFFEE-01",
        name_snapshot="Coffee",
        quantity=1,
        prices_include_tax=True,
        unit_price_minor=quote_total_minor,
        option_total_minor=0,
        discount_minor=0,
        tax_category_code="BEVERAGE",
        tax_rate_ppm=90000,
        net_minor=net_minor,
        tax_minor=tax_minor,
        line_total_minor=quote_total_minor,
        preparation_snapshot={"recipe": "espresso"},
        allergen_snapshot={"contains": []},
    )
    quote_tax = PriceQuoteTaxLine(
        quote_id=quote_id,
        tax_category_code="BEVERAGE",
        tax_rate_ppm=90000,
        taxable_minor=net_minor,
        tax_minor=tax_minor,
    )

    async with database.session_factory() as session, session.begin():
        session.add(tenant)
        await session.flush()
        session.add_all([legal_entity, user, category, price_book, tax_policy])
        await session.flush()
        session.add(store)
        await session.flush()
        session.add_all([policy, kiosk, station, product])
        await session.flush()
        session.add_all([endpoint, terminal, quote])
        await session.flush()
        session.add_all([quote_item, quote_tax])
        await session.flush()

        if order_id is not None and attempt_id is not None:
            order = SalesOrder(
                id=order_id,
                tenant_id=tenant_id,
                store_id=store_id,
                kiosk_id=kiosk_id,
                quote_id=quote_id,
                business_date=now.date(),
                sequence_number=1,
                order_number="AMS-20260812-000001",
                display_number="001",
                status=OrderStatus.DRAFT,
                payment_status=PaymentStatus.INITIATED,
                currency="EUR",
                locale="nl-NL",
                prices_include_tax=True,
                subtotal_minor=quote_total_minor,
                discount_minor=0,
                net_minor=net_minor,
                tax_minor=tax_minor,
                total_minor=quote_total_minor,
            )
            session.add(order)
            await session.flush()
            order_item = OrderItem(
                order_id=order_id,
                line_number=1,
                product_id=product_id,
                sku_snapshot="COFFEE-01",
                name_snapshot="Coffee",
                quantity=1,
                prices_include_tax=True,
                unit_price_minor=quote_total_minor,
                option_total_minor=0,
                discount_minor=0,
                tax_category_code="BEVERAGE",
                tax_rate_ppm=90000,
                net_minor=net_minor,
                tax_minor=tax_minor,
                line_total_minor=quote_total_minor,
                preparation_snapshot={"recipe": "espresso"},
                allergen_snapshot={"contains": []},
            )
            order_tax = OrderTaxLine(
                order_id=order_id,
                tax_category_code="BEVERAGE",
                tax_rate_ppm=90000,
                taxable_minor=net_minor,
                tax_minor=tax_minor,
            )
            attempt = PaymentAttempt(
                id=attempt_id,
                order_id=order_id,
                attempt_number=1,
                provider=PaymentProvider.MOCK,
                payment_method=PaymentMethod.CARD,
                terminal_id=terminal_id,
                status=PaymentStatus.INITIATED,
                amount_minor=quote_total_minor,
                currency="EUR",
                merchant_reference="AMS-20260812-000001",
                provider_service_id=f"mock-service-{attempt_id}",
                requested_at=now,
            )
            initial_event = OrderStatusEvent(
                order_id=order_id,
                sequence_number=1,
                from_status=None,
                to_status=OrderStatus.DRAFT,
                actor_type=ActorType.KIOSK,
                actor_device_id=kiosk_id,
                occurred_at=now,
            )
            session.add_all([order_item, order_tax, attempt, initial_event])

    return SeedData(
        tenant_id=tenant_id,
        store_id=store_id,
        kiosk_id=kiosk_id,
        station_id=station_id,
        endpoint_id=endpoint_id,
        terminal_id=terminal_id,
        user_id=user_id,
        quote_id=quote_id,
        order_id=order_id,
        attempt_id=attempt_id,
    )


@pytest.fixture
async def ordering_database(
    anyio_backend: str,
) -> AsyncIterator[tuple[Database, SeedData]]:
    del anyio_backend
    database = await _create_database()
    seed = await _seed_store(database, include_order=False)
    try:
        yield database, seed
    finally:
        await database.dispose()


@pytest.fixture
async def payment_database(
    anyio_backend: str,
) -> AsyncIterator[tuple[Database, SeedData]]:
    del anyio_backend
    database = await _create_database()
    seed = await _seed_store(database, include_order=True)
    try:
        yield database, seed
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_create_order_snapshots_quote_and_replays_same_idempotency_key(
    ordering_database: tuple[Database, SeedData],
) -> None:
    database, seed = ordering_database
    settings = Settings(app_env="test", mock_payment_enabled=True)

    async with database.session_factory() as session, session.begin():
        created = await create_order(
            session,
            settings,
            kiosk_id=seed.kiosk_id,
            store_id=seed.store_id,
            quote_id=seed.quote_id,
            payment_method=PaymentMethod.CARD,
            idempotency_key="order-key-1",
        )
    async with database.session_factory() as session, session.begin():
        replayed = await create_order(
            session,
            settings,
            kiosk_id=seed.kiosk_id,
            store_id=seed.store_id,
            quote_id=seed.quote_id,
            payment_method=PaymentMethod.CARD,
            idempotency_key="order-key-1",
        )

    assert replayed.id == created.id
    assert created.status == OrderStatus.DRAFT
    assert created.payment_status == PaymentStatus.INITIATED
    assert created.total_minor == 1000
    assert created.items[0].name == "Coffee"
    assert len(created.payment_attempts) == 1

    async with database.session_factory() as session:
        order_count = await session.scalar(select(func.count(SalesOrder.id)))
        attempt_count = await session.scalar(select(func.count(PaymentAttempt.id)))
        idempotency_count = await session.scalar(select(func.count(IdempotencyRecord.id)))
        audit_count = await session.scalar(select(func.count(AuditLog.id)))
        outbox_count = await session.scalar(select(func.count(OutboxEvent.id)))
        quote = await session.get(PriceQuote, seed.quote_id)
        stored_item = await session.scalar(select(OrderItem))

    assert order_count == 1
    assert attempt_count == 1
    assert idempotency_count == 1
    assert audit_count == 1
    assert outbox_count == 1
    assert quote is not None
    assert quote.status == QuoteStatus.CONSUMED
    assert stored_item is not None
    assert stored_item.preparation_snapshot == {"recipe": "espresso"}

    with pytest.raises(ConflictError) as conflict:
        async with database.session_factory() as session, session.begin():
            await create_order(
                session,
                settings,
                kiosk_id=seed.kiosk_id,
                store_id=seed.store_id,
                quote_id=seed.quote_id,
                payment_method=PaymentMethod.CONTACTLESS,
                idempotency_key="order-key-1",
            )
    assert conflict.value.code == "idempotency_key_reused"


@pytest.mark.anyio
async def test_concurrent_order_retries_with_one_key_create_one_order(
    anyio_backend: str,
    tmp_path: Path,
) -> None:
    del anyio_backend
    database_path = (tmp_path / "idempotency.sqlite3").as_posix()
    database = await _create_database(f"sqlite+aiosqlite:///{database_path}")
    seed = await _seed_store(database, include_order=False)
    settings = Settings(app_env="test", mock_payment_enabled=True)

    async def submit() -> UUID:
        async with database.session_factory() as session, session.begin():
            response = await create_order(
                session,
                settings,
                kiosk_id=seed.kiosk_id,
                store_id=seed.store_id,
                quote_id=seed.quote_id,
                payment_method=PaymentMethod.CARD,
                idempotency_key="same-concurrent-order",
            )
            return response.id

    try:
        first_id, second_id = await asyncio.gather(submit(), submit())
        assert first_id == second_id
        async with database.session_factory() as session:
            assert await session.scalar(select(func.count(SalesOrder.id))) == 1
            assert await session.scalar(select(func.count(PaymentAttempt.id))) == 1
            assert await session.scalar(select(func.count(IdempotencyRecord.id))) == 1
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_create_order_rejects_a_non_positive_payment_total(anyio_backend: str) -> None:
    del anyio_backend
    database = await _create_database()
    seed = await _seed_store(database, include_order=False, quote_total_minor=0)
    settings = Settings(app_env="test", mock_payment_enabled=True)
    try:
        with pytest.raises(ConflictError) as conflict:
            async with database.session_factory() as session, session.begin():
                await create_order(
                    session,
                    settings,
                    kiosk_id=seed.kiosk_id,
                    store_id=seed.store_id,
                    quote_id=seed.quote_id,
                    payment_method=PaymentMethod.CARD,
                    idempotency_key="zero-total-order",
                )
        assert conflict.value.code == "quote_not_payable"
        async with database.session_factory() as session:
            assert await session.scalar(select(func.count(SalesOrder.id))) == 0
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_create_order_rejects_a_non_reconciling_quote_snapshot(
    ordering_database: tuple[Database, SeedData],
) -> None:
    database, seed = ordering_database
    settings = Settings(app_env="test", mock_payment_enabled=True)
    async with database.session_factory() as session, session.begin():
        quote = await session.get(PriceQuote, seed.quote_id)
        assert quote is not None
        quote.subtotal_minor += 1
        quote.net_minor += 1
        quote.total_minor += 1

    with pytest.raises(ConflictError) as conflict:
        async with database.session_factory() as session, session.begin():
            await create_order(
                session,
                settings,
                kiosk_id=seed.kiosk_id,
                store_id=seed.store_id,
                quote_id=seed.quote_id,
                payment_method=PaymentMethod.CARD,
                idempotency_key="invalid-quote-snapshot",
            )
    assert conflict.value.code == "quote_snapshot_invalid"

    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(SalesOrder.id))) == 0
        assert await session.scalar(select(func.count(IdempotencyRecord.id))) == 0


@pytest.mark.anyio
async def test_create_order_rejects_a_quote_with_mismatched_tax_buckets(
    ordering_database: tuple[Database, SeedData],
) -> None:
    database, seed = ordering_database
    settings = Settings(app_env="test", mock_payment_enabled=True)
    async with database.session_factory() as session, session.begin():
        tax_line = await session.scalar(
            select(PriceQuoteTaxLine).where(PriceQuoteTaxLine.quote_id == seed.quote_id)
        )
        assert tax_line is not None
        tax_line.tax_category_code = "CORRUPTED-CATEGORY"

    with pytest.raises(ConflictError) as conflict:
        async with database.session_factory() as session, session.begin():
            await create_order(
                session,
                settings,
                kiosk_id=seed.kiosk_id,
                store_id=seed.store_id,
                quote_id=seed.quote_id,
                payment_method=PaymentMethod.CARD,
                idempotency_key="mismatched-tax-buckets",
            )
    assert conflict.value.code == "quote_snapshot_invalid"

    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(SalesOrder.id))) == 0
        assert await session.scalar(select(func.count(IdempotencyRecord.id))) == 0


@pytest.mark.anyio
async def test_paid_authorization_releases_all_order_artifacts_atomically(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None

    response = await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    assert response.status == OrderStatus.CONFIRMED
    assert response.payment_status == PaymentStatus.PAID
    assert response.paid_minor == response.total_minor == 1000

    async with database.session_factory() as session:
        transactions = list((await session.scalars(select(PaymentTransaction))).all())
        tickets = list((await session.scalars(select(FulfillmentTicket))).all())
        ticket_items = list((await session.scalars(select(FulfillmentTicketItem))).all())
        fulfillment_events = list((await session.scalars(select(FulfillmentEvent))).all())
        receipts = list((await session.scalars(select(Receipt))).all())
        audit_actions = list((await session.scalars(select(AuditLog.action))).all())
        outbox_types = list((await session.scalars(select(OutboxEvent.event_type))).all())
        order_events = list((await session.scalars(select(OrderStatusEvent))).all())
        refund_count = await session.scalar(select(func.count(Refund.id)))

    assert len(transactions) == 1
    assert transactions[0].transaction_kind == PaymentTransactionKind.AUTHORISATION
    assert transactions[0].status == PaymentStatus.PAID
    assert len(tickets) == 1
    assert tickets[0].status == FulfillmentStatus.QUEUED
    assert len(ticket_items) == 1
    assert len(fulfillment_events) == 1
    assert len(receipts) == 1
    assert receipts[0].receipt_type == ReceiptType.SALE
    assert "order.confirmed" in audit_actions
    assert set(outbox_types) == {"order.confirmed", "fulfillment.ticket.created"}
    assert len(order_events) == 2
    assert refund_count == 0


@pytest.mark.anyio
async def test_paid_authorization_with_no_active_default_opens_manual_review(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    async with database.session_factory() as session, session.begin():
        station = await session.get(KitchenStation, seed.station_id)
        assert station is not None
        station.is_default = False

    response = await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    assert response.status == OrderStatus.CONFIRMED
    assert response.payment_status == PaymentStatus.PAID
    assert response.paid_minor == response.total_minor
    async with database.session_factory() as session:
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        ticket = await session.scalar(select(FulfillmentTicket))
        review = await session.scalar(select(ManualReviewCase))
        audit_actions = set((await session.scalars(select(AuditLog.action))).all())
        outbox_types = set((await session.scalars(select(OutboxEvent.event_type))).all())

        assert attempt is not None
        assert attempt.status == PaymentStatus.PAID
        assert ticket is not None
        assert ticket.status == FulfillmentStatus.UNFULFILLABLE
        assert (
            ticket.failure_reason_code
            == FulfillmentFailureReason.MANUAL_WORKSTATION_EQUIPMENT_FAILURE
        )
        assert review is not None
        assert review.fulfillment_ticket_id == ticket.id
        assert review.status == ReviewStatus.OPEN
        assert await session.scalar(select(func.count(PaymentTransaction.id))) == 1
        assert await session.scalar(select(func.count(Receipt.id))) == 1
        assert await session.scalar(select(func.count(Refund.id))) == 0

    assert {"order.confirmed", "manual_review.opened", "fulfillment.release_blocked"} <= (
        audit_actions
    )
    assert {
        "order.confirmed",
        "fulfillment.ticket.created",
        "manual_review.opened",
        "fulfillment.release_blocked",
    } <= outbox_types


@pytest.mark.anyio
async def test_inactive_default_does_not_make_active_default_ambiguous(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    async with database.session_factory() as session, session.begin():
        session.add(
            KitchenStation(
                store_id=seed.store_id,
                code="RETIRED-BAR",
                name="Retired Bar",
                is_default=True,
                active=False,
            )
        )

    response = await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    assert response.status == OrderStatus.CONFIRMED
    assert response.payment_status == PaymentStatus.PAID
    async with database.session_factory() as session:
        ticket = await session.scalar(select(FulfillmentTicket))
        assert ticket is not None
        assert ticket.station_id == seed.station_id
        assert ticket.status == FulfillmentStatus.QUEUED
        assert await session.scalar(select(func.count(ManualReviewCase.id))) == 0


@pytest.mark.anyio
async def test_paid_authorization_without_any_station_keeps_payment_fact_and_alerts(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    async with database.session_factory() as session, session.begin():
        endpoint = await session.get(FulfillmentEndpoint, seed.endpoint_id)
        station = await session.get(KitchenStation, seed.station_id)
        assert endpoint is not None
        assert station is not None
        await session.delete(endpoint)
        await session.flush()
        await session.delete(station)

    response = await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    assert response.status == OrderStatus.CONFIRMED
    assert response.payment_status == PaymentStatus.PAID
    async with database.session_factory() as session:
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        outbox_types = set((await session.scalars(select(OutboxEvent.event_type))).all())
        audit_actions = set((await session.scalars(select(AuditLog.action))).all())
        assert attempt is not None
        assert attempt.status == PaymentStatus.PAID
        assert await session.scalar(select(func.count(PaymentTransaction.id))) == 1
        assert await session.scalar(select(func.count(Receipt.id))) == 1
        assert await session.scalar(select(func.count(FulfillmentTicket.id))) == 0
        review = await session.scalar(select(ManualReviewCase))
        assert review is not None
        assert review.order_id == seed.order_id
        assert review.fulfillment_ticket_id is None
        assert review.status == ReviewStatus.OPEN
        assert review.reason_code == FulfillmentFailureReason.MANUAL_WORKSTATION_EQUIPMENT_FAILURE

    assert "fulfillment.release_blocked" in audit_actions
    assert "fulfillment.release_blocked" in outbox_types
    assert "manual_review.opened" in audit_actions
    assert "manual_review.opened" in outbox_types

    principal = Principal(
        user_id=seed.user_id,
        tenant_id=seed.tenant_id,
        permissions=frozenset({"review:resolve"}),
        store_ids=frozenset({seed.store_id}),
    )
    async with database.session_factory() as session, session.begin():
        review = await session.scalar(select(ManualReviewCase))
        assert review is not None
        resolved = await resolve_review(
            session,
            principal,
            case_id=review.id,
            request=ResolveReviewRequest(
                expected_version=review.version,
                resolution=ReviewResolution.FULL_REFUND,
                notes="No fulfillment station was configured",
            ),
            idempotency_key="refund-no-station-order",
        )
        refund = await session.scalar(select(Refund))
        assert resolved.status == ReviewStatus.ACTION_PENDING
        assert refund is not None
        refund_id = refund.id

    refund_response = await payment_service.execute_refund(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        principal,
        refund_id=refund_id,
    )
    assert refund_response.status == RefundStatus.SUCCEEDED
    async with database.session_factory() as session:
        order = await session.get(SalesOrder, seed.order_id)
        review = await session.scalar(select(ManualReviewCase))
        assert order is not None and review is not None
        assert order.status == OrderStatus.CLOSED
        assert order.payment_status == PaymentStatus.REFUNDED
        assert review.status == ReviewStatus.RESOLVED


@pytest.mark.anyio
async def test_amount_drift_stops_before_calling_the_payment_provider(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    async with database.session_factory() as session, session.begin():
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        assert attempt is not None
        attempt.amount_minor = 900

    adapter = CountingMockPaymentAdapter(MockPaymentScenario.APPROVED)
    with pytest.raises(ConflictError) as conflict:
        await payment_service.execute_authorization(
            database,
            adapter,
            kiosk_id=seed.kiosk_id,
            attempt_id=seed.attempt_id,
        )
    assert conflict.value.code == "payment_order_amount_mismatch"
    assert adapter.authorize_calls == 0

    async with database.session_factory() as session:
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        assert attempt is not None
        assert attempt.status == PaymentStatus.INITIATED
        assert await session.scalar(select(func.count(PaymentTransaction.id))) == 0
        assert await session.scalar(select(func.count(FulfillmentTicket.id))) == 0


@pytest.mark.anyio
async def test_declined_payment_can_create_one_idempotent_retry_attempt(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.order_id is not None
    assert seed.attempt_id is not None
    declined = await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.DECLINED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )
    assert declined.payment_status == PaymentStatus.FAILED

    settings = Settings(app_env="test", mock_payment_enabled=True)
    async with database.session_factory() as session, session.begin():
        retried = await create_retry_payment_attempt(
            session,
            settings,
            kiosk_id=seed.kiosk_id,
            store_id=seed.store_id,
            order_id=seed.order_id,
            payment_method=PaymentMethod.CONTACTLESS,
            idempotency_key="retry-failed-payment",
        )
    async with database.session_factory() as session, session.begin():
        replayed = await create_retry_payment_attempt(
            session,
            settings,
            kiosk_id=seed.kiosk_id,
            store_id=seed.store_id,
            order_id=seed.order_id,
            payment_method=PaymentMethod.CONTACTLESS,
            idempotency_key="retry-failed-payment",
        )
    assert replayed.id == retried.id
    assert retried.payment_status == PaymentStatus.INITIATED
    assert [attempt.status for attempt in retried.payment_attempts] == [
        PaymentStatus.FAILED,
        PaymentStatus.INITIATED,
    ]

    retry_attempt = retried.payment_attempts[-1]
    paid = await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=retry_attempt.id,
    )
    assert paid.status == OrderStatus.CONFIRMED
    assert paid.payment_status == PaymentStatus.PAID
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(PaymentAttempt.id))) == 2
        assert await session.scalar(select(func.count(FulfillmentTicket.id))) == 1


@pytest.mark.anyio
async def test_failed_payment_attempt_cannot_later_transition_to_paid(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.DECLINED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    with pytest.raises(ConflictError) as conflict:
        await payment_service.apply_authorization_result(
            database,
            attempt_id=seed.attempt_id,
            result=AuthorizationResult(
                provider=PaymentProvider.MOCK,
                provider_event_id="late-paid-after-decline",
                status=PaymentStatus.PAID,
                psp_reference="LATE-PSP",
            ),
        )
    assert conflict.value.code == "payment_attempt_terminal"

    async with database.session_factory() as session:
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        order = await session.get(SalesOrder, seed.order_id)
        assert attempt is not None
        assert attempt.status == PaymentStatus.FAILED
        assert order is not None
        assert order.status == OrderStatus.DRAFT
        assert order.payment_status == PaymentStatus.FAILED
        assert await session.scalar(select(func.count(PaymentTransaction.id))) == 1
        assert await session.scalar(select(func.count(FulfillmentTicket.id))) == 0


@pytest.mark.anyio
async def test_failed_payment_attempt_cannot_be_reconciled(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    adapter = CountingMockPaymentAdapter(MockPaymentScenario.DECLINED)
    await payment_service.execute_authorization(
        database,
        adapter,
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    with pytest.raises(ConflictError) as conflict:
        await payment_service.execute_authorization(
            database,
            adapter,
            kiosk_id=seed.kiosk_id,
            attempt_id=seed.attempt_id,
            reconcile=True,
        )

    assert conflict.value.code == "payment_not_reconcilable"
    assert adapter.authorize_calls == 1


@pytest.mark.anyio
async def test_reconciliation_preserves_previous_safe_provider_metadata(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    await payment_service.apply_authorization_result(
        database,
        attempt_id=seed.attempt_id,
        result=AuthorizationResult(
            provider=PaymentProvider.MOCK,
            provider_event_id="initial-unknown-with-reference",
            status=PaymentStatus.UNKNOWN,
            psp_reference="SAFE-PSP-REFERENCE",
            card_brand="TEST",
            masked_account="•••• 1111",
            failure_code="RESULT_UNKNOWN",
        ),
    )
    paid = await payment_service.apply_authorization_result(
        database,
        attempt_id=seed.attempt_id,
        result=AuthorizationResult(
            provider=PaymentProvider.MOCK,
            provider_event_id="reconciled-paid-without-metadata",
            status=PaymentStatus.PAID,
        ),
    )

    assert paid.payment_status == PaymentStatus.PAID
    async with database.session_factory() as session:
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        assert attempt is not None
        assert attempt.psp_reference == "SAFE-PSP-REFERENCE"
        assert attempt.card_brand == "TEST"
        assert attempt.masked_account == "•••• 1111"


@pytest.mark.anyio
async def test_paid_release_rolls_back_as_one_database_transaction(
    payment_database: tuple[Database, SeedData],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database, seed = payment_database
    assert seed.order_id is not None
    assert seed.attempt_id is not None

    async def fail_receipt(*_: object) -> NoReturn:
        raise RuntimeError("receipt persistence failed")

    monkeypatch.setattr(payment_service, "create_sale_receipt", fail_receipt)
    with pytest.raises(RuntimeError, match="receipt persistence failed"):
        await payment_service.execute_authorization(
            database,
            MockPaymentAdapter(MockPaymentScenario.APPROVED),
            kiosk_id=seed.kiosk_id,
            attempt_id=seed.attempt_id,
        )

    async with database.session_factory() as session:
        order = await session.get(SalesOrder, seed.order_id)
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        transaction_count = await session.scalar(select(func.count(PaymentTransaction.id)))
        ticket_count = await session.scalar(select(func.count(FulfillmentTicket.id)))
        receipt_count = await session.scalar(select(func.count(Receipt.id)))
        audit_count = await session.scalar(select(func.count(AuditLog.id)))
        outbox_count = await session.scalar(select(func.count(OutboxEvent.id)))
        order_event_count = await session.scalar(select(func.count(OrderStatusEvent.id)))

    assert order is not None
    assert order.status == OrderStatus.DRAFT
    assert order.payment_status == PaymentStatus.INITIATED
    assert order.paid_minor == 0
    assert attempt is not None
    assert attempt.status == PaymentStatus.AUTHORIZING
    assert transaction_count == 0
    assert ticket_count == 0
    assert receipt_count == 0
    assert audit_count == 0
    assert outbox_count == 0
    assert order_event_count == 1


@pytest.mark.anyio
async def test_fulfillment_heartbeat_and_state_version_are_authoritative(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )
    endpoint_principal = FulfillmentEndpointPrincipal(
        endpoint_id=seed.endpoint_id,
        station_id=seed.station_id,
    )

    async with database.session_factory() as session, session.begin():
        endpoint_id, station_id, heartbeat_at, version = await heartbeat_endpoint(
            session,
            endpoint_principal,
        )
    assert endpoint_id == seed.endpoint_id
    assert station_id == seed.station_id
    assert version == 2

    async with database.session_factory() as session, session.begin():
        ticket = await session.scalar(select(FulfillmentTicket))
        endpoint = await session.get(FulfillmentEndpoint, seed.endpoint_id)
        assert ticket is not None
        assert endpoint is not None
        assert endpoint.last_heartbeat_at == heartbeat_at
        with pytest.raises(ConflictError) as stale:
            await transition_ticket(
                session,
                endpoint_principal,
                ticket_id=ticket.id,
                to_status=FulfillmentStatus.ACKNOWLEDGED,
                expected_version=ticket.version + 1,
                failure_reason_code=None,
                failure_detail=None,
            )
        assert stale.value.code == "stale_version"

    async with database.session_factory() as session, session.begin():
        ticket = await session.scalar(select(FulfillmentTicket))
        assert ticket is not None
        acknowledged = await transition_ticket(
            session,
            endpoint_principal,
            ticket_id=ticket.id,
            to_status=FulfillmentStatus.ACKNOWLEDGED,
            expected_version=ticket.version,
            failure_reason_code=None,
            failure_detail=None,
        )
        with pytest.raises(ConflictError) as invalid:
            await transition_ticket(
                session,
                endpoint_principal,
                ticket_id=ticket.id,
                to_status=FulfillmentStatus.COLLECTED,
                expected_version=acknowledged.version,
                failure_reason_code=None,
                failure_detail=None,
            )
        assert invalid.value.code == "invalid_fulfillment_transition"


@pytest.mark.anyio
async def test_fulfillment_hides_and_rejects_cross_store_ticket_corruption(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    other_store_id = uuid4()
    other_station_id = uuid4()
    other_endpoint_id = uuid4()
    async with database.session_factory() as session, session.begin():
        legal_entity_id = await session.scalar(select(LegalEntity.id))
        assert legal_entity_id is not None
        session.add(
            Store(
                id=other_store_id,
                legal_entity_id=legal_entity_id,
                code="AMS-02",
                name="Amsterdam Other Store",
                country_code="NL",
                currency="EUR",
                locale="nl-NL",
                timezone="Europe/Amsterdam",
            )
        )
        await session.flush()
        session.add(
            KitchenStation(
                id=other_station_id,
                store_id=other_store_id,
                code="BAR-02",
                name="Other Bar",
                is_default=True,
            )
        )
        await session.flush()
        session.add(
            FulfillmentEndpoint(
                id=other_endpoint_id,
                station_id=other_station_id,
                endpoint_type=FulfillmentEndpointType.KDS,
                external_reference="KDS-OTHER",
                credential_hash="x" * 64,
                last_heartbeat_at=utc_now(),
            )
        )
        await session.flush()
        ticket = await session.scalar(select(FulfillmentTicket))
        assert ticket is not None
        ticket.station_id = other_station_id
        await session.flush()

    endpoint_principal = FulfillmentEndpointPrincipal(
        endpoint_id=other_endpoint_id,
        station_id=other_station_id,
    )
    async with database.session_factory() as session, session.begin():
        assert await list_station_queue(session, endpoint_principal) == []
        ticket = await session.scalar(select(FulfillmentTicket))
        assert ticket is not None
        with pytest.raises(ConflictError) as mismatch:
            await transition_ticket(
                session,
                endpoint_principal,
                ticket_id=ticket.id,
                to_status=FulfillmentStatus.ACKNOWLEDGED,
                expected_version=ticket.version,
                failure_reason_code=None,
                failure_detail=None,
            )
        assert mismatch.value.code == "fulfillment_store_mismatch"


@pytest.mark.anyio
async def test_unknown_payment_never_releases_order_and_reconciles_without_duplicates(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    adapter = MockPaymentAdapter(MockPaymentScenario.UNKNOWN)

    unknown = await payment_service.execute_authorization(
        database,
        adapter,
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )
    assert unknown.status == OrderStatus.DRAFT
    assert unknown.payment_status == PaymentStatus.UNKNOWN
    assert unknown.paid_minor == 0

    async with database.session_factory() as session:
        transaction = await session.scalar(select(PaymentTransaction))
        assert transaction is not None
        unknown_event_id = transaction.provider_event_id
        assert await session.scalar(select(func.count(FulfillmentTicket.id))) == 0
        assert await session.scalar(select(func.count(Receipt.id))) == 0
        assert await session.scalar(select(func.count(Refund.id))) == 0
        assert await session.scalar(select(func.count(ManualReviewCase.id))) == 0

    with pytest.raises(ConflictError) as retry_conflict:
        await payment_service.execute_authorization(
            database,
            adapter,
            kiosk_id=seed.kiosk_id,
            attempt_id=seed.attempt_id,
        )
    assert retry_conflict.value.code == "payment_result_unknown"

    with pytest.raises(ConflictError) as event_conflict:
        await payment_service.apply_authorization_result(
            database,
            attempt_id=seed.attempt_id,
            result=AuthorizationResult(
                provider=PaymentProvider.MOCK,
                provider_event_id=unknown_event_id,
                status=PaymentStatus.PAID,
                psp_reference="CONFLICTING-PSP-REFERENCE",
            ),
        )
    assert event_conflict.value.code == "payment_event_conflict"

    still_unknown = await payment_service.execute_authorization(
        database,
        adapter,
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
        reconcile=True,
    )
    assert still_unknown.payment_status == PaymentStatus.UNKNOWN

    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(PaymentTransaction.id))) == 1
        assert await session.scalar(select(func.count(OutboxEvent.id))) == 1
        assert await session.scalar(select(func.count(AuditLog.id))) == 1
        assert await session.scalar(select(func.count(FulfillmentTicket.id))) == 0
        assert await session.scalar(select(func.count(Receipt.id))) == 0

    adapter.scenario = MockPaymentScenario.APPROVED
    paid = await payment_service.execute_authorization(
        database,
        adapter,
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
        reconcile=True,
    )
    assert paid.status == OrderStatus.CONFIRMED
    assert paid.payment_status == PaymentStatus.PAID

    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(PaymentTransaction.id))) == 2
        assert await session.scalar(select(func.count(FulfillmentTicket.id))) == 1
        assert await session.scalar(select(func.count(Receipt.id))) == 1
        assert await session.scalar(select(func.count(Refund.id))) == 0


def test_staff_workflow_inputs_reject_cardholder_authentication_data() -> None:
    with pytest.raises(ValidationError):
        TransitionTicketRequest(
            to_status=FulfillmentStatus.UNFULFILLABLE,
            expected_version=1,
            failure_reason_code=FulfillmentFailureReason.OTHER,
            failure_detail="Customer wrote CVV=123 on the terminal",
        )
    with pytest.raises(ValidationError):
        ResolveReviewRequest(
            expected_version=1,
            resolution=ReviewResolution.SUBSTITUTION,
            notes="Card 4111111111111111 was shown to staff",
            payload={},
        )
    with pytest.raises(ValidationError):
        ResolveReviewRequest(
            expected_version=1,
            resolution=ReviewResolution.SUBSTITUTION,
            payload={"cvv": "123"},
        )


@pytest.mark.anyio
async def test_unfulfillable_paid_order_opens_review_without_automatic_refund(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    async with database.session_factory() as session:
        ticket = await session.scalar(select(FulfillmentTicket))
    assert ticket is not None
    endpoint = FulfillmentEndpointPrincipal(
        endpoint_id=seed.endpoint_id,
        station_id=seed.station_id,
    )
    async with database.session_factory() as session, session.begin():
        transitioned = await transition_ticket(
            session,
            endpoint,
            ticket_id=ticket.id,
            to_status=FulfillmentStatus.UNFULFILLABLE,
            expected_version=ticket.version,
            failure_reason_code=FulfillmentFailureReason.OUT_OF_STOCK,
            failure_detail="Ingredient unavailable",
        )
    assert transitioned.status == FulfillmentStatus.UNFULFILLABLE

    async with database.session_factory() as session:
        review = await session.scalar(select(ManualReviewCase))
        refund_count = await session.scalar(select(func.count(Refund.id)))
    assert review is not None
    assert review.order_id == ticket.order_id
    assert review.fulfillment_ticket_id == ticket.id
    assert review.reason_code == FulfillmentFailureReason.OUT_OF_STOCK
    assert refund_count == 0


@pytest.mark.anyio
async def test_refund_changes_money_only_after_provider_confirmation(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.order_id is not None
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    refund_id = uuid4()
    async with database.session_factory() as session, session.begin():
        order = await session.get(SalesOrder, seed.order_id)
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        assert order is not None
        assert attempt is not None
        order.payment_status = PaymentStatus.REFUND_PENDING
        order.version += 1
        attempt.status = PaymentStatus.REFUND_PENDING
        attempt.version += 1
        session.add(
            Refund(
                id=refund_id,
                order_id=order.id,
                payment_attempt_id=attempt.id,
                request_key_hash="r" * 64,
                amount_minor=1000,
                currency="EUR",
                reason_code="OUT_OF_STOCK",
                status=RefundStatus.PENDING,
                requested_by=seed.user_id,
            )
        )

    unknown_result = RefundResult(
        provider=PaymentProvider.MOCK,
        provider_event_id="refund-unknown-event",
        status=RefundStatus.UNKNOWN,
        failure_code="RESULT_UNKNOWN",
    )
    unknown = await payment_service.apply_refund_result(
        database,
        refund_id=refund_id,
        result=unknown_result,
    )
    replayed_unknown = await payment_service.apply_refund_result(
        database,
        refund_id=refund_id,
        result=unknown_result,
    )
    assert unknown.status == RefundStatus.UNKNOWN
    assert replayed_unknown.version == unknown.version

    async with database.session_factory() as session:
        order = await session.get(SalesOrder, seed.order_id)
        refund_transaction_count = await session.scalar(
            select(func.count(PaymentTransaction.id)).where(
                PaymentTransaction.transaction_kind == PaymentTransactionKind.REFUND
            )
        )
        refund_outbox_count = await session.scalar(
            select(func.count(OutboxEvent.id)).where(OutboxEvent.aggregate_type == "refund")
        )
        refund_receipt_count = await session.scalar(
            select(func.count(Receipt.id)).where(Receipt.refund_id == refund_id)
        )
    assert order is not None
    assert order.refunded_minor == 0
    assert order.payment_status == PaymentStatus.REFUND_PENDING
    assert refund_transaction_count == 1
    assert refund_outbox_count == 1
    assert refund_receipt_count == 0

    reconciliation_principal = Principal(
        user_id=seed.user_id,
        tenant_id=seed.tenant_id,
        permissions=frozenset({"payment:reconcile"}),
        store_ids=frozenset({seed.store_id}),
    )
    reconciliation_adapter = ObservingRefundAdapter(database)
    succeeded = await payment_service.execute_refund(
        database,
        reconciliation_adapter,
        reconciliation_principal,
        refund_id=refund_id,
        reconcile=True,
    )
    assert succeeded.status == RefundStatus.SUCCEEDED
    assert reconciliation_adapter.request_audit_visible_during_provider_call
    assert reconciliation_adapter.request_audit_action == "refund.reconciliation_requested"
    assert reconciliation_adapter.request_audit_actor_user_id == seed.user_id

    async with database.session_factory() as session:
        order = await session.get(SalesOrder, seed.order_id)
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        refund_receipt = await session.scalar(select(Receipt).where(Receipt.refund_id == refund_id))
        refund_transaction_count = await session.scalar(
            select(func.count(PaymentTransaction.id)).where(
                PaymentTransaction.transaction_kind == PaymentTransactionKind.REFUND
            )
        )
        refund_receipt_count = await session.scalar(
            select(func.count(Receipt.id)).where(Receipt.refund_id == refund_id)
        )
        reconciliation_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.target_id == refund_id,
                AuditLog.action == "refund.reconciliation_requested",
            )
        )
        provider_result_audit_count = await session.scalar(
            select(func.count(AuditLog.id)).where(
                AuditLog.target_id == refund_id,
                AuditLog.action == "refund.status_changed",
                AuditLog.actor_type == ActorType.PROVIDER,
            )
        )
    assert order is not None
    assert order.refunded_minor == 1000
    assert order.payment_status == PaymentStatus.REFUNDED
    assert attempt is not None
    assert attempt.status == PaymentStatus.REFUNDED
    assert refund_receipt is not None
    assert refund_id.hex.upper() in refund_receipt.receipt_number
    assert len(refund_receipt.receipt_number) <= 100
    assert refund_transaction_count == 2
    assert refund_receipt_count == 1
    assert reconciliation_audit is not None
    assert reconciliation_audit.actor_type == ActorType.USER
    assert reconciliation_audit.actor_user_id == seed.user_id
    assert reconciliation_audit.metadata_redacted == {
        "amount_minor": 1000,
        "currency": "EUR",
        "provider": "MOCK",
        "request_type": "RECONCILE",
    }
    assert provider_result_audit_count == 2


@pytest.mark.anyio
async def test_refund_external_call_is_claimed_before_contacting_provider(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.order_id is not None
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )
    refund_id = uuid4()
    async with database.session_factory() as session, session.begin():
        order = await session.get(SalesOrder, seed.order_id)
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        assert order is not None
        assert attempt is not None
        order.payment_status = PaymentStatus.REFUND_PENDING
        attempt.status = PaymentStatus.REFUND_PENDING
        session.add(
            Refund(
                id=refund_id,
                order_id=order.id,
                payment_attempt_id=attempt.id,
                request_key_hash="claim-before-provider",
                amount_minor=order.paid_minor,
                currency=order.currency,
                reason_code="OUT_OF_STOCK",
                status=RefundStatus.PENDING,
                requested_by=seed.user_id,
            )
        )

    principal = Principal(
        user_id=seed.user_id,
        tenant_id=seed.tenant_id,
        permissions=frozenset({"review:resolve"}),
        store_ids=frozenset({seed.store_id}),
    )
    adapter = ObservingRefundAdapter(database)
    response = await payment_service.execute_refund(
        database,
        adapter,
        principal,
        refund_id=refund_id,
    )
    assert adapter.status_during_provider_call == RefundStatus.UNKNOWN
    assert adapter.request_audit_visible_during_provider_call
    assert adapter.request_audit_action == "refund.execution_requested"
    assert adapter.request_audit_actor_user_id == seed.user_id
    assert response.status == RefundStatus.SUCCEEDED
    async with database.session_factory() as session:
        request_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.target_id == refund_id,
                AuditLog.action == "refund.execution_requested",
            )
        )
        provider_result_audit = await session.scalar(
            select(AuditLog).where(
                AuditLog.target_id == refund_id,
                AuditLog.action == "refund.status_changed",
                AuditLog.actor_type == ActorType.PROVIDER,
            )
        )
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
    assert request_audit is not None
    assert request_audit.actor_type == ActorType.USER
    assert request_audit.actor_user_id == seed.user_id
    assert request_audit.before_redacted == {"status": "PENDING", "version": 1}
    assert request_audit.after_redacted == {"status": "UNKNOWN", "version": 2}
    assert request_audit.metadata_redacted == {
        "amount_minor": 1000,
        "currency": "EUR",
        "provider": "MOCK",
        "request_type": "EXECUTE",
    }
    assert provider_result_audit is not None
    assert provider_result_audit.actor_type == ActorType.PROVIDER
    assert attempt is not None and attempt.psp_reference is not None
    serialized_request_audit = json.dumps(
        {
            "before": request_audit.before_redacted,
            "after": request_audit.after_redacted,
            "metadata": request_audit.metadata_redacted,
        },
        sort_keys=True,
    )
    assert attempt.psp_reference not in serialized_request_audit
    assert "psp_reference" not in serialized_request_audit


@pytest.mark.anyio
async def test_pending_refund_cannot_be_reconciled_before_it_is_executed(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.order_id is not None
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )
    refund_id = uuid4()
    async with database.session_factory() as session, session.begin():
        session.add(
            Refund(
                id=refund_id,
                order_id=seed.order_id,
                payment_attempt_id=seed.attempt_id,
                request_key_hash="pending-refund-reconcile",
                amount_minor=1000,
                currency="EUR",
                reason_code="OUT_OF_STOCK",
                status=RefundStatus.PENDING,
                requested_by=seed.user_id,
            )
        )

    principal = Principal(
        user_id=seed.user_id,
        tenant_id=seed.tenant_id,
        permissions=frozenset({"payment:reconcile"}),
        store_ids=frozenset({seed.store_id}),
    )
    with pytest.raises(ConflictError) as conflict:
        await payment_service.execute_refund(
            database,
            MockPaymentAdapter(MockPaymentScenario.APPROVED),
            principal,
            refund_id=refund_id,
            reconcile=True,
        )
    assert conflict.value.code == "refund_not_reconcilable"

    async with database.session_factory() as session:
        refund = await session.get(Refund, refund_id)
        order = await session.get(SalesOrder, seed.order_id)
        assert refund is not None
        assert refund.status == RefundStatus.PENDING
        assert order is not None
        assert order.refunded_minor == 0
        assert (
            await session.scalar(
                select(func.count(PaymentTransaction.id)).where(
                    PaymentTransaction.transaction_kind == PaymentTransactionKind.REFUND
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count(AuditLog.id)).where(
                    AuditLog.target_id == refund_id,
                    AuditLog.action == "refund.reconciliation_requested",
                )
            )
            == 0
        )


@pytest.mark.anyio
async def test_failed_refund_is_terminal_and_requires_a_new_refund_request(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.order_id is not None
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )
    refund_id = uuid4()
    async with database.session_factory() as session, session.begin():
        session.add(
            Refund(
                id=refund_id,
                order_id=seed.order_id,
                payment_attempt_id=seed.attempt_id,
                request_key_hash="failed-refund-terminal",
                amount_minor=1000,
                currency="EUR",
                reason_code="OUT_OF_STOCK",
                status=RefundStatus.PENDING,
                requested_by=seed.user_id,
            )
        )
    await payment_service.apply_refund_result(
        database,
        refund_id=refund_id,
        result=RefundResult(
            provider=PaymentProvider.MOCK,
            provider_event_id="refund-terminal-failed",
            status=RefundStatus.FAILED,
            failure_code="DECLINED",
        ),
    )

    with pytest.raises(ConflictError) as conflict:
        await payment_service.apply_refund_result(
            database,
            refund_id=refund_id,
            result=RefundResult(
                provider=PaymentProvider.MOCK,
                provider_event_id="refund-late-success",
                status=RefundStatus.SUCCEEDED,
                psp_reference="LATE-REFUND-PSP",
            ),
        )
    assert conflict.value.code == "refund_terminal_state_conflict"

    principal = Principal(
        user_id=seed.user_id,
        tenant_id=seed.tenant_id,
        permissions=frozenset({"payment:reconcile"}),
        store_ids=frozenset({seed.store_id}),
    )
    with pytest.raises(ConflictError) as reconcile_conflict:
        await payment_service.execute_refund(
            database,
            MockPaymentAdapter(MockPaymentScenario.APPROVED),
            principal,
            refund_id=refund_id,
            reconcile=True,
        )
    assert reconcile_conflict.value.code == "refund_not_reconcilable"

    async with database.session_factory() as session:
        refund = await session.get(Refund, refund_id)
        order = await session.get(SalesOrder, seed.order_id)
        assert refund is not None
        assert refund.status == RefundStatus.FAILED
        assert order is not None
        assert order.refunded_minor == 0
        assert order.payment_status == PaymentStatus.PAID
        assert (
            await session.scalar(
                select(func.count(PaymentTransaction.id)).where(
                    PaymentTransaction.transaction_kind == PaymentTransactionKind.REFUND
                )
            )
            == 1
        )


@pytest.mark.anyio
async def test_payment_provider_metadata_cannot_persist_unmasked_card_data(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None

    unsafe_result = AuthorizationResult(
        provider=PaymentProvider.MOCK,
        provider_event_id="4111111111111111",
        status=PaymentStatus.PAID,
        psp_reference="PSP 4111111111111111",
        card_brand="VISA 4111111111111111",
        masked_account="4111111111111111",
        failure_code="CVV=123",
        failure_detail_redacted="PIN=9999 card=4111111111111111",
    )
    await payment_service.apply_authorization_result(
        database,
        attempt_id=seed.attempt_id,
        result=unsafe_result,
    )

    async with database.session_factory() as session:
        attempt = await session.get(PaymentAttempt, seed.attempt_id)
        transaction = await session.scalar(select(PaymentTransaction))
    assert attempt is not None
    assert transaction is not None
    assert attempt.masked_account is None
    assert "4111111111111111" not in (attempt.card_brand or "")
    assert "4111111111111111" not in (attempt.failure_detail_redacted or "")
    assert "123" not in (attempt.failure_code or "")
    assert "9999" not in (attempt.failure_detail_redacted or "")
    assert "4111111111111111" not in transaction.provider_event_id
    assert "4111111111111111" not in (transaction.psp_reference or "")
    assert "123" not in str(transaction.payload_redacted)
    assert transaction.payload_hash != canonical_json_hash(asdict(unsafe_result))

    await payment_service.apply_authorization_result(
        database,
        attempt_id=seed.attempt_id,
        result=unsafe_result,
    )
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(PaymentTransaction.id))) == 1


@pytest.mark.anyio
async def test_receipt_integrity_mismatch_is_not_silently_returned(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )
    async with database.session_factory() as session, session.begin():
        receipt = await session.scalar(select(Receipt))
        assert receipt is not None
        tampered = dict(receipt.document_snapshot)
        tampered["currency"] = "USD"
        receipt.document_snapshot = tampered

    async with database.session_factory() as session:
        receipt = await session.scalar(select(Receipt))
        assert receipt is not None
        with pytest.raises(ConflictError) as integrity_error:
            to_receipt_response(receipt)
    assert integrity_error.value.code == "receipt_integrity_failed"


@pytest.mark.anyio
async def test_successful_review_refund_closes_the_terminal_order(
    payment_database: tuple[Database, SeedData],
) -> None:
    database, seed = payment_database
    assert seed.order_id is not None
    assert seed.attempt_id is not None
    await payment_service.execute_authorization(
        database,
        MockPaymentAdapter(MockPaymentScenario.APPROVED),
        kiosk_id=seed.kiosk_id,
        attempt_id=seed.attempt_id,
    )

    principal = Principal(
        user_id=seed.user_id,
        tenant_id=seed.tenant_id,
        permissions=frozenset({"kitchen:operate", "review:resolve"}),
        store_ids=frozenset({seed.store_id}),
    )
    endpoint = FulfillmentEndpointPrincipal(
        endpoint_id=seed.endpoint_id,
        station_id=seed.station_id,
    )
    async with database.session_factory() as session, session.begin():
        ticket = await session.scalar(select(FulfillmentTicket))
        assert ticket is not None
        await transition_ticket(
            session,
            endpoint,
            ticket_id=ticket.id,
            to_status=FulfillmentStatus.UNFULFILLABLE,
            expected_version=ticket.version,
            failure_reason_code=FulfillmentFailureReason.OUT_OF_STOCK,
            failure_detail="Ingredient unavailable",
        )

    async with database.session_factory() as session, session.begin():
        review = await session.scalar(select(ManualReviewCase))
        assert review is not None
        resolved = await resolve_review(
            session,
            principal,
            case_id=review.id,
            request=ResolveReviewRequest(
                expected_version=review.version,
                resolution=ReviewResolution.FULL_REFUND,
            ),
            idempotency_key="review-full-refund",
        )
        assert resolved.status == ReviewStatus.ACTION_PENDING

    async with database.session_factory() as session, session.begin():
        replayed = await resolve_review(
            session,
            principal,
            case_id=resolved.id,
            request=ResolveReviewRequest(
                expected_version=resolved.version - 1,
                resolution=ReviewResolution.FULL_REFUND,
            ),
            idempotency_key="review-full-refund",
        )
        assert replayed.id == resolved.id
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(Refund.id))) == 1

    with pytest.raises(ConflictError) as pending_conflict:
        async with database.session_factory() as session, session.begin():
            await resolve_review(
                session,
                principal,
                case_id=resolved.id,
                request=ResolveReviewRequest(
                    expected_version=resolved.version,
                    resolution=ReviewResolution.FULL_REFUND,
                ),
                idempotency_key="second-review-refund-while-pending",
            )
    assert pending_conflict.value.code == "review_action_pending"
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(Refund.id))) == 1

    async with database.session_factory() as session:
        refund = await session.scalar(select(Refund))
    assert refund is not None
    await payment_service.apply_refund_result(
        database,
        refund_id=refund.id,
        result=RefundResult(
            provider=PaymentProvider.MOCK,
            provider_event_id="review-refund-succeeded",
            status=RefundStatus.SUCCEEDED,
            psp_reference="MOCK-REVIEW-REFUND",
        ),
    )

    async with database.session_factory() as session:
        order = await session.get(SalesOrder, seed.order_id)
        review = await session.scalar(select(ManualReviewCase))
    assert order is not None
    assert order.status == OrderStatus.CLOSED
    assert order.payment_status == PaymentStatus.REFUNDED
    assert review is not None
    assert review.status == ReviewStatus.RESOLVED
