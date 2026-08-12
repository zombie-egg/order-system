from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select

import app.persistence.models  # noqa: F401
from app.core.config import Settings
from app.core.enums import PromotionType
from app.core.errors import ConflictError
from app.core.principals import Principal
from app.modules.audit.models import AuditLog
from app.modules.catalog.models import OptionValue, StoreProductAvailability
from app.modules.catalog.schemas import (
    CreateCategoryRequest,
    CreateOptionGroupRequest,
    CreateOptionValueInput,
    CreatePriceBookRequest,
    CreateProductRequest,
    PriceBookOptionPriceInput,
    PriceBookProductInput,
    ProductOptionRuleInput,
    ProductTranslationInput,
)
from app.modules.catalog.service import (
    create_category,
    create_option_group,
    create_price_book,
    create_product,
    get_store_catalog,
    set_product_availability,
)
from app.modules.identity.models import UserAccount
from app.modules.organization.models import (
    KioskDevice,
    LegalEntity,
    Store,
    StoreOperatingPolicy,
    Tenant,
)
from app.modules.pricing_tax.models import PriceQuoteItem
from app.modules.pricing_tax.schemas import (
    CreatePromotionRequest,
    CreateQuoteRequest,
    CreateTaxPolicyRequest,
    QuoteItemRequest,
    TaxRateInput,
)
from app.modules.pricing_tax.service import create_promotion, create_quote, create_tax_policy
from app.persistence.base import Base
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class CommerceSeed:
    tenant_id: UUID
    user_id: UUID
    store_id: UUID
    kiosk_id: UUID
    product_id: UUID
    allowed_option_value_id: UUID
    disallowed_option_value_id: UUID


async def _database() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return database


async def _seed_commerce(database: Database) -> CommerceSeed:
    tenant_id = uuid4()
    legal_entity_id = uuid4()
    store_id = uuid4()
    kiosk_id = uuid4()
    user_id = uuid4()
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
    policy = StoreOperatingPolicy(store_id=store_id, accepting_orders=True)
    kiosk = KioskDevice(
        id=kiosk_id,
        store_id=store_id,
        code="KIOSK-01",
        display_name="Kiosk 1",
        credential_hash="k" * 64,
    )
    user = UserAccount(
        id=user_id,
        tenant_id=tenant_id,
        username="catalog-manager",
        username_normalized="catalog-manager",
        display_name="Catalog Manager",
        password_hash="not-used-in-this-test",
    )
    principal = Principal(
        user_id=user_id,
        tenant_id=tenant_id,
        permissions=frozenset({"catalog:write"}),
        store_ids=frozenset({store_id}),
    )
    async with database.session_factory() as session, session.begin():
        session.add(tenant)
        await session.flush()
        session.add_all([legal_entity, user])
        await session.flush()
        session.add(store)
        await session.flush()
        session.add_all([policy, kiosk])
        category = await create_category(
            session,
            principal,
            CreateCategoryRequest(
                store_id=store_id,
                code="Drinks",
                translations={"nl-NL": "Dranken", "en": "Drinks"},
            ),
        )
        allowed_group = await create_option_group(
            session,
            principal,
            CreateOptionGroupRequest(
                store_id=store_id,
                code="size",
                translations={"nl-NL": "Formaat", "en": "Size"},
                values=[
                    CreateOptionValueInput(
                        code="large",
                        translations={"nl-NL": "Groot", "en": "Large"},
                    )
                ],
            ),
        )
        disallowed_group = await create_option_group(
            session,
            principal,
            CreateOptionGroupRequest(
                store_id=store_id,
                code="internal",
                translations={"en": "Internal"},
                values=[
                    CreateOptionValueInput(
                        code="hidden",
                        translations={"en": "Hidden"},
                    )
                ],
            ),
        )
        product = await create_product(
            session,
            principal,
            CreateProductRequest(
                store_id=store_id,
                category_id=category.id,
                sku="COFFEE-01",
                tax_category_code="BEVERAGE",
                translations={
                    "nl-NL": ProductTranslationInput(name="Koffie"),
                    "en": ProductTranslationInput(name="Coffee"),
                },
                preparation_data={"recipe": "commercial-secret"},
                allergen_data={"contains": []},
                option_rules=[
                    ProductOptionRuleInput(
                        option_group_id=allowed_group.id,
                        minimum_selections=1,
                        maximum_selections=1,
                    )
                ],
            ),
        )
        await session.flush()
        allowed_value_id = await session.scalar(
            select(OptionValue.id).where(OptionValue.option_group_id == allowed_group.id)
        )
        disallowed_value_id = await session.scalar(
            select(OptionValue.id).where(OptionValue.option_group_id == disallowed_group.id)
        )
        assert allowed_value_id is not None
        assert disallowed_value_id is not None
    return CommerceSeed(
        tenant_id=tenant_id,
        user_id=user_id,
        store_id=store_id,
        kiosk_id=kiosk_id,
        product_id=product.id,
        allowed_option_value_id=allowed_value_id,
        disallowed_option_value_id=disallowed_value_id,
    )


@pytest.fixture
async def commerce_database(
    anyio_backend: str,
) -> AsyncIterator[tuple[Database, CommerceSeed]]:
    del anyio_backend
    database = await _database()
    seed = await _seed_commerce(database)
    try:
        yield database, seed
    finally:
        await database.dispose()


def _principal(seed: CommerceSeed) -> Principal:
    return Principal(
        user_id=seed.user_id,
        tenant_id=seed.tenant_id,
        permissions=frozenset({"catalog:write"}),
        store_ids=frozenset({seed.store_id}),
    )


@pytest.mark.anyio
async def test_authoritative_quote_reconciles_price_discount_and_inclusive_vat(
    commerce_database: tuple[Database, CommerceSeed],
) -> None:
    database, seed = commerce_database
    now = datetime.now(UTC)
    principal = _principal(seed)
    async with database.session_factory() as session, session.begin():
        store = await session.get(Store, seed.store_id)
        assert store is not None
        await create_tax_policy(
            session,
            principal,
            store,
            CreateTaxPolicyRequest(
                store_id=seed.store_id,
                version=1,
                valid_from=now - timedelta(days=1),
                rates=[TaxRateInput(tax_category_code="BEVERAGE", rate_ppm=90_000)],
            ),
        )
        await create_price_book(
            session,
            principal,
            CreatePriceBookRequest(
                store_id=seed.store_id,
                code="default",
                version=1,
                currency="EUR",
                valid_from=now - timedelta(hours=1),
                items=[
                    PriceBookProductInput(
                        product_id=seed.product_id,
                        price_minor=1_000,
                        option_prices=[
                            PriceBookOptionPriceInput(
                                option_value_id=seed.allowed_option_value_id,
                                price_delta_minor=100,
                            )
                        ],
                    )
                ],
            ),
        )
        await create_promotion(
            session,
            principal,
            CreatePromotionRequest(
                store_id=seed.store_id,
                code="SAVE10",
                name="Ten percent",
                promotion_type=PromotionType.PERCENTAGE,
                value=100_000,
                starts_at=now - timedelta(hours=1),
            ),
        )

    async with database.session_factory() as session, session.begin():
        quote = await create_quote(
            session,
            Settings(app_env="test"),
            store_id=seed.store_id,
            kiosk_id=seed.kiosk_id,
            request=CreateQuoteRequest(
                locale="en",
                promotion_code="SAVE10",
                items=[
                    QuoteItemRequest(
                        product_id=seed.product_id,
                        quantity=2,
                        option_value_ids=[seed.allowed_option_value_id],
                    )
                ],
            ),
        )
        stored_item = await session.scalar(select(PriceQuoteItem))

    assert quote.subtotal_minor == 2_200
    assert quote.discount_minor == 220
    assert quote.net_minor == 1_817
    assert quote.tax_minor == 163
    assert quote.total_minor == 1_980
    assert quote.net_minor + quote.tax_minor == quote.total_minor
    assert quote.items[0].name == "Coffee"
    assert quote.items[0].allergen_snapshot == {"contains": []}
    assert "preparation_snapshot" not in quote.items[0].model_dump()
    assert stored_item is not None
    assert stored_item.preparation_snapshot == {"recipe": "commercial-secret"}
    async with database.session_factory() as session:
        audit_actions = set((await session.scalars(select(AuditLog.action))).all())
    assert {
        "pricing.price_book.created",
        "pricing.promotion.created",
        "pricing.tax_policy.created",
    } <= audit_actions


@pytest.mark.anyio
async def test_public_catalog_does_not_expose_internal_preparation_data(
    commerce_database: tuple[Database, CommerceSeed],
) -> None:
    database, seed = commerce_database
    now = datetime.now(UTC)
    async with database.session_factory() as session, session.begin():
        await create_price_book(
            session,
            _principal(seed),
            CreatePriceBookRequest(
                store_id=seed.store_id,
                code="default",
                version=1,
                currency="EUR",
                valid_from=now - timedelta(hours=1),
                items=[
                    PriceBookProductInput(
                        product_id=seed.product_id,
                        price_minor=1_000,
                        option_prices=[
                            PriceBookOptionPriceInput(
                                option_value_id=seed.allowed_option_value_id,
                                price_delta_minor=100,
                            )
                        ],
                    )
                ],
            ),
        )
        catalog = await get_store_catalog(session, seed.store_id, "en")

    product = catalog.categories[0].products[0]
    assert product.name == "Coffee"
    assert product.allergen_data == {"contains": []}
    assert "preparation_data" not in product.model_dump()
    assert "commercial-secret" not in catalog.model_dump_json()


@pytest.mark.anyio
async def test_price_book_rejects_an_option_not_allowed_for_the_product(
    commerce_database: tuple[Database, CommerceSeed],
) -> None:
    database, seed = commerce_database
    with pytest.raises(ConflictError) as conflict:
        async with database.session_factory() as session, session.begin():
            await create_price_book(
                session,
                _principal(seed),
                CreatePriceBookRequest(
                    store_id=seed.store_id,
                    code="invalid",
                    version=1,
                    currency="EUR",
                    valid_from=datetime.now(UTC),
                    items=[
                        PriceBookProductInput(
                            product_id=seed.product_id,
                            price_minor=1_000,
                            option_prices=[
                                PriceBookOptionPriceInput(
                                    option_value_id=seed.disallowed_option_value_id,
                                    price_delta_minor=100,
                                )
                            ],
                        )
                    ],
                ),
            )
    assert conflict.value.code == "invalid_option_price"


@pytest.mark.anyio
async def test_product_availability_rejects_a_stale_optimistic_version(
    commerce_database: tuple[Database, CommerceSeed],
) -> None:
    database, seed = commerce_database
    async with database.session_factory() as session, session.begin():
        updated = await set_product_availability(
            session,
            _principal(seed),
            seed.store_id,
            seed.product_id,
            available=False,
            expected_version=1,
        )
        assert updated.available is False
        assert updated.version == 2

    with pytest.raises(ConflictError) as conflict:
        async with database.session_factory() as session, session.begin():
            await set_product_availability(
                session,
                _principal(seed),
                seed.store_id,
                seed.product_id,
                available=True,
                expected_version=1,
            )
    assert conflict.value.code == "stale_version"

    async with database.session_factory() as session:
        availability = await session.get(
            StoreProductAvailability,
            (seed.store_id, seed.product_id),
        )
        assert availability is not None
        assert availability.available is False
        assert availability.version == 2


def test_catalog_inputs_reject_duplicate_price_rows_and_naive_validity() -> None:
    product_id = uuid4()
    with pytest.raises(ValidationError):
        CreatePriceBookRequest(
            store_id=uuid4(),
            code="duplicate",
            version=1,
            currency="EUR",
            valid_from=datetime.now(),
            items=[
                PriceBookProductInput(product_id=product_id, price_minor=100),
                PriceBookProductInput(product_id=product_id, price_minor=200),
            ],
        )


def test_product_input_limits_internal_json_payload_size() -> None:
    with pytest.raises(ValidationError):
        CreateProductRequest(
            store_id=uuid4(),
            category_id=uuid4(),
            sku="TOO-LARGE",
            tax_category_code="beverage",
            translations={"en": ProductTranslationInput(name="Large")},
            preparation_data={"recipe": "x" * 40_000},
        )


def test_product_internal_json_rejects_payment_card_authentication_data() -> None:
    with pytest.raises(ValidationError):
        CreateProductRequest(
            store_id=uuid4(),
            category_id=uuid4(),
            sku="UNSAFE-METADATA",
            tax_category_code="beverage",
            translations={"en": ProductTranslationInput(name="Unsafe")},
            preparation_data={"card_number": "4111111111111111"},
        )
