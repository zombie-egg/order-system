from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

import app.persistence.models  # noqa: F401
from app.api.dependencies import Principal, get_current_principal
from app.core.enums import (
    FulfillmentFailureReason,
    FulfillmentStatus,
    OrderStatus,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    PriceBookStatus,
    QuoteStatus,
    ReceiptType,
    RefundStatus,
)
from app.core.errors import DomainError
from app.modules.audit.service import canonical_hash
from app.modules.catalog.models import PriceBook
from app.modules.identity.models import UserAccount
from app.modules.kitchen_fulfillment.models import FulfillmentTicket
from app.modules.ordering.models import SalesOrder
from app.modules.organization.models import KioskDevice, KitchenStation, LegalEntity, Store, Tenant
from app.modules.payments.models import (
    PaymentAttempt,
    ReconciliationIssue,
    ReconciliationRun,
    Refund,
)
from app.modules.pricing_tax.models import PriceQuote, TaxPolicyVersion
from app.modules.receipts.models import Receipt
from app.modules.receipts.router import admin_router as receipt_admin_router
from app.modules.receipts.service import get_sale_receipt_for_staff
from app.modules.reporting.router import router as reporting_router
from app.persistence.base import Base
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class SeedData:
    tenant_id: UUID
    store_id: UUID
    sale_receipt_id: UUID
    refund_receipt_id: UUID


def _principal(seed: SeedData, *, report_read: bool = True) -> Principal:
    permissions = frozenset({"report:read"}) if report_read else frozenset()
    return Principal(
        user_id=uuid4(),
        tenant_id=seed.tenant_id,
        permissions=permissions,
        store_ids=frozenset({seed.store_id}),
    )


def _test_app(database: Database, principal: Principal) -> FastAPI:
    application = FastAPI()
    application.state.database = database
    application.include_router(receipt_admin_router, prefix="/api/v1")
    application.include_router(reporting_router, prefix="/api/v1")

    @application.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content={"title": exc.code, "detail": exc.message, "details": exc.details},
        )

    async def override_principal() -> Principal:
        return principal

    application.dependency_overrides[get_current_principal] = override_principal
    return application


@pytest.fixture
async def seeded_database(anyio_backend: str) -> AsyncIterator[tuple[Database, SeedData]]:
    del anyio_backend
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    tenant_id = uuid4()
    legal_entity_id = uuid4()
    store_id = uuid4()
    kiosk_id = uuid4()
    station_id = uuid4()
    user_id = uuid4()
    price_book_id = uuid4()
    tax_policy_id = uuid4()
    first_quote_id = uuid4()
    second_quote_id = uuid4()
    first_order_id = uuid4()
    second_order_id = uuid4()
    first_attempt_id = uuid4()
    second_attempt_id = uuid4()
    succeeded_refund_id = uuid4()
    sale_receipt_id = uuid4()
    refund_receipt_id = uuid4()
    now = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
    business_date = date(2026, 8, 11)

    tenant = Tenant(id=tenant_id, code="tenant", name="Test Tenant")
    legal_entity = LegalEntity(
        id=legal_entity_id,
        tenant_id=tenant_id,
        code="entity",
        name="Test Entity",
        country_code="NL",
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
    user = UserAccount(
        id=user_id,
        tenant_id=tenant_id,
        username="reporter",
        username_normalized="reporter",
        display_name="Reporter",
        password_hash="not-used-in-this-test",
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
    first_quote = PriceQuote(
        id=first_quote_id,
        store_id=store_id,
        kiosk_id=kiosk_id,
        price_book_id=price_book_id,
        tax_policy_version_id=tax_policy_id,
        status=QuoteStatus.CONSUMED,
        request_hash="a" * 64,
        currency="EUR",
        locale="nl-NL",
        prices_include_tax=True,
        subtotal_minor=1000,
        discount_minor=0,
        net_minor=830,
        tax_minor=170,
        total_minor=1000,
        snapshot={},
        expires_at=now + timedelta(minutes=15),
        consumed_at=now,
        created_at=now,
    )
    second_quote = PriceQuote(
        id=second_quote_id,
        store_id=store_id,
        kiosk_id=kiosk_id,
        price_book_id=price_book_id,
        tax_policy_version_id=tax_policy_id,
        status=QuoteStatus.CONSUMED,
        request_hash="b" * 64,
        currency="EUR",
        locale="nl-NL",
        prices_include_tax=True,
        subtotal_minor=500,
        discount_minor=0,
        net_minor=415,
        tax_minor=85,
        total_minor=500,
        snapshot={},
        expires_at=now + timedelta(minutes=15),
        consumed_at=now,
        created_at=now,
    )
    first_order = SalesOrder(
        id=first_order_id,
        tenant_id=tenant_id,
        store_id=store_id,
        kiosk_id=kiosk_id,
        quote_id=first_quote_id,
        business_date=business_date,
        sequence_number=1,
        order_number="AMS-20260811-0001",
        display_number="0001",
        status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.PARTIALLY_REFUNDED,
        currency="EUR",
        locale="nl-NL",
        prices_include_tax=True,
        subtotal_minor=1000,
        discount_minor=0,
        net_minor=830,
        tax_minor=170,
        total_minor=1000,
        paid_minor=1000,
        refunded_minor=200,
        confirmed_at=now,
        created_at=now,
    )
    second_order = SalesOrder(
        id=second_order_id,
        tenant_id=tenant_id,
        store_id=store_id,
        kiosk_id=kiosk_id,
        quote_id=second_quote_id,
        business_date=business_date,
        sequence_number=2,
        order_number="AMS-20260811-0002",
        display_number="0002",
        status=OrderStatus.CLOSED,
        payment_status=PaymentStatus.PAID,
        currency="EUR",
        locale="nl-NL",
        prices_include_tax=True,
        subtotal_minor=500,
        discount_minor=0,
        net_minor=415,
        tax_minor=85,
        total_minor=500,
        paid_minor=500,
        refunded_minor=0,
        confirmed_at=now + timedelta(minutes=30),
        closed_at=now + timedelta(minutes=45),
        created_at=now + timedelta(minutes=25),
    )
    first_attempt = PaymentAttempt(
        id=first_attempt_id,
        order_id=first_order_id,
        attempt_number=1,
        provider=PaymentProvider.MOCK,
        payment_method=PaymentMethod.CARD,
        status=PaymentStatus.PAID,
        amount_minor=1000,
        currency="EUR",
        merchant_reference="payment-1",
        provider_service_id="mock-payment-1",
        requested_at=now,
        completed_at=now,
    )
    second_attempt = PaymentAttempt(
        id=second_attempt_id,
        order_id=second_order_id,
        attempt_number=1,
        provider=PaymentProvider.MOCK,
        payment_method=PaymentMethod.CARD,
        status=PaymentStatus.PAID,
        amount_minor=500,
        currency="EUR",
        merchant_reference="payment-2",
        provider_service_id="mock-payment-2",
        requested_at=now + timedelta(minutes=30),
        completed_at=now + timedelta(minutes=30),
    )
    succeeded_refund = Refund(
        id=succeeded_refund_id,
        order_id=first_order_id,
        payment_attempt_id=first_attempt_id,
        request_key_hash="c" * 64,
        amount_minor=200,
        currency="EUR",
        reason_code="CUSTOMER_REQUEST",
        status=RefundStatus.SUCCEEDED,
        requested_by=user_id,
        psp_reference="refund-1",
        completed_at=now + timedelta(hours=1),
        created_at=now + timedelta(hours=1),
    )
    pending_refund = Refund(
        id=uuid4(),
        order_id=second_order_id,
        payment_attempt_id=second_attempt_id,
        request_key_hash="d" * 64,
        amount_minor=100,
        currency="EUR",
        reason_code="REVIEW_PENDING",
        status=RefundStatus.PENDING,
        requested_by=user_id,
        created_at=now + timedelta(hours=2),
    )
    sale_document = {"schema_version": 1, "amounts": {"total_minor": 1000}}
    sale_receipt = Receipt(
        id=sale_receipt_id,
        store_id=store_id,
        order_id=first_order_id,
        receipt_type=ReceiptType.SALE,
        receipt_number="AMS-20260811-0001",
        business_date=business_date,
        locale="nl-NL",
        currency="EUR",
        document_snapshot=sale_document,
        content_hash=canonical_hash(sale_document),
        generated_at=now,
    )
    refund_document = {"schema_version": 1, "amount_minor": 200}
    refund_receipt = Receipt(
        id=refund_receipt_id,
        store_id=store_id,
        order_id=first_order_id,
        refund_id=succeeded_refund_id,
        receipt_type=ReceiptType.REFUND,
        receipt_number="R-AMS-20260811-0001",
        business_date=business_date,
        locale="nl-NL",
        currency="EUR",
        document_snapshot=refund_document,
        content_hash=canonical_hash(refund_document),
        generated_at=now + timedelta(hours=1),
    )
    collected_ticket = FulfillmentTicket(
        id=uuid4(),
        order_id=first_order_id,
        station_id=station_id,
        generation_number=1,
        display_number="0001",
        status=FulfillmentStatus.COLLECTED,
        priority=0,
        preparation_snapshot={},
        acknowledged_by=user_id,
        acknowledged_at=now + timedelta(minutes=1),
        started_by=user_id,
        started_at=now + timedelta(minutes=2),
        ready_by=user_id,
        ready_at=now + timedelta(minutes=5),
        collected_by=user_id,
        collected_at=now + timedelta(minutes=7),
        created_at=now,
    )
    failed_ticket = FulfillmentTicket(
        id=uuid4(),
        order_id=second_order_id,
        station_id=station_id,
        generation_number=1,
        display_number="0002",
        status=FulfillmentStatus.UNFULFILLABLE,
        priority=0,
        preparation_snapshot={},
        failure_reason_code=FulfillmentFailureReason.OUT_OF_STOCK,
        created_at=now + timedelta(minutes=30),
    )
    reconciliation_run = ReconciliationRun(
        id=uuid4(),
        store_id=store_id,
        provider=PaymentProvider.MOCK,
        status="COMPLETED",
        started_at=now + timedelta(hours=3),
        completed_at=now + timedelta(hours=3, minutes=5),
    )
    reconciliation_issue = ReconciliationIssue(
        id=uuid4(),
        run_id=reconciliation_run.id,
        issue_code="REFUND_MISMATCH",
        severity="CRITICAL",
        resource_type="refund",
        resource_id=succeeded_refund_id,
        details={"expected_minor": 200},
    )

    async with database.session_factory() as session:
        session.add(tenant)
        await session.flush()
        session.add_all([legal_entity, user, price_book, tax_policy])
        await session.flush()
        session.add(store)
        await session.flush()
        session.add_all([kiosk, station, reconciliation_run])
        await session.flush()
        session.add_all([first_quote, second_quote])
        await session.flush()
        session.add_all([first_order, second_order])
        await session.flush()
        session.add_all(
            [first_attempt, second_attempt, collected_ticket, failed_ticket, reconciliation_issue]
        )
        await session.flush()
        session.add_all([succeeded_refund, pending_refund, sale_receipt])
        await session.flush()
        session.add(refund_receipt)
        await session.commit()

    seed = SeedData(
        tenant_id=tenant_id,
        store_id=store_id,
        sale_receipt_id=sale_receipt_id,
        refund_receipt_id=refund_receipt_id,
    )
    try:
        yield database, seed
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_staff_reads_stored_sale_and_refund_receipts(
    seeded_database: tuple[Database, SeedData],
) -> None:
    database, seed = seeded_database
    principal = _principal(seed)
    async with database.session_factory() as session:
        detached = await get_sale_receipt_for_staff(session, principal, seed.sale_receipt_id)
        detached.document["amounts"]["total_minor"] = 1
        stored = await session.get(Receipt, seed.sale_receipt_id)
        assert stored is not None
        assert stored.document_snapshot["amounts"]["total_minor"] == 1000

    application = _test_app(database, principal)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sale = await client.get(f"/api/v1/admin/receipts/sales/{seed.sale_receipt_id}")
        refund = await client.get(f"/api/v1/admin/receipts/refunds/{seed.refund_receipt_id}")
        sale_again = await client.get(f"/api/v1/admin/receipts/sales/{seed.sale_receipt_id}")

    assert sale.status_code == 200
    assert sale.json()["receipt_type"] == "SALE"
    assert sale.json()["document"] == {"schema_version": 1, "amounts": {"total_minor": 1000}}
    assert sale_again.json() == sale.json()
    assert refund.status_code == 200
    assert refund.json()["receipt_type"] == "REFUND"
    assert refund.json()["document"] == {"schema_version": 1, "amount_minor": 200}


@pytest.mark.anyio
async def test_receipts_and_reports_require_report_read(
    seeded_database: tuple[Database, SeedData],
) -> None:
    database, seed = seeded_database
    application = _test_app(database, _principal(seed, report_read=False))
    params = {
        "store_id": str(seed.store_id),
        "start_at": "2026-08-11T00:00:00Z",
        "end_at": "2026-08-12T00:00:00Z",
    }
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        receipt = await client.get(f"/api/v1/admin/receipts/sales/{seed.sale_receipt_id}")
        report = await client.get("/api/v1/admin/reports/sales", params=params)

    assert receipt.status_code == 403
    assert report.status_code == 403


@pytest.mark.anyio
async def test_staff_reporting_summaries(
    seeded_database: tuple[Database, SeedData],
) -> None:
    database, seed = seeded_database
    application = _test_app(database, _principal(seed))
    params = {
        "store_id": str(seed.store_id),
        "start_at": "2026-08-11T00:00:00Z",
        "end_at": "2026-08-12T00:00:00Z",
    }
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        sales = await client.get("/api/v1/admin/reports/sales", params=params)
        refunds = await client.get("/api/v1/admin/reports/refunds", params=params)
        fulfillment = await client.get("/api/v1/admin/reports/fulfillment", params=params)
        reconciliation = await client.get("/api/v1/admin/reports/reconciliation", params=params)

    assert sales.status_code == 200
    assert sales.json()["order_count"] == 2
    assert sales.json()["gross_sales_minor"] == 1500
    assert sales.json()["paid_minor"] == 1500
    assert sales.json()["refunded_minor"] == 200
    assert sales.json()["net_collected_minor"] == 1300

    assert refunds.status_code == 200
    assert refunds.json()["refund_count"] == 2
    assert refunds.json()["requested_minor"] == 300
    assert refunds.json()["succeeded_minor"] == 200
    assert refunds.json()["status_counts"]["SUCCEEDED"] == 1
    assert refunds.json()["status_counts"]["PENDING"] == 1

    assert fulfillment.status_code == 200
    assert fulfillment.json()["ticket_count"] == 2
    assert fulfillment.json()["status_counts"]["COLLECTED"] == 1
    assert fulfillment.json()["status_counts"]["UNFULFILLABLE"] == 1
    assert fulfillment.json()["average_seconds_to_acknowledge"] == 60
    assert fulfillment.json()["average_seconds_to_ready"] == 300
    assert fulfillment.json()["average_seconds_ready_to_collect"] == 120

    assert reconciliation.status_code == 200
    assert reconciliation.json()["run_count"] == 1
    assert reconciliation.json()["completed_run_count"] == 1
    assert reconciliation.json()["open_issue_count"] == 1
    assert reconciliation.json()["critical_open_issue_count"] == 1
    assert reconciliation.json()["latest_run_status"] == "COMPLETED"
