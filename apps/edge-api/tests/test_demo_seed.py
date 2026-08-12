from __future__ import annotations

from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.demo_seed as demo_seed_module
import app.persistence.models  # noqa: F401
from app.bootstrap import BootstrapResult
from app.core.config import Settings
from app.core.errors import ConflictError
from app.core.security import verify_device_credential, verify_password
from app.demo_seed import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_USERNAME,
    DEMO_ENDPOINT_KEY,
    DEMO_KIOSK_KEY,
    DEMO_PRODUCTS,
    DEMO_TENANT_CODE,
    seed_demo_store,
)
from app.modules.catalog.models import (
    Category,
    OptionGroup,
    PriceBook,
    Product,
    StorePriceBookAssignment,
)
from app.modules.catalog.service import get_store_catalog
from app.modules.identity.models import UserAccount
from app.modules.organization.models import (
    FulfillmentEndpoint,
    KioskDevice,
    StoreOperatingPolicy,
    Tenant,
)
from app.modules.pricing_tax.models import TaxPolicyVersion, TaxRate
from app.persistence.base import Base
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _database() -> Database:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return database


def _settings(
    *,
    app_env: Literal["development", "test", "staging", "production"] = "test",
) -> Settings:
    return Settings(
        app_env=app_env,
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="demo-seed-test-secret-that-is-at-least-thirty-two-bytes",
        mock_payment_enabled=(app_env in {"development", "test"}),
    )


@pytest.mark.anyio
async def test_seed_demo_creates_operable_netherlands_store_and_is_idempotent() -> None:
    database = await _database()
    try:
        async with database.session_factory() as session, session.begin():
            first = await seed_demo_store(session, _settings())
        async with database.session_factory() as session, session.begin():
            second = await seed_demo_store(session, _settings())

        assert first.created is True
        assert second.created is False
        assert second.tenant_id == first.tenant_id
        assert second.store_id == first.store_id
        assert second.owner_user_id == first.owner_user_id
        assert first.tenant_code == DEMO_TENANT_CODE
        assert first.owner_username == DEMO_ADMIN_USERNAME
        assert first.owner_password == DEMO_ADMIN_PASSWORD
        assert first.kiosk_key == DEMO_KIOSK_KEY
        assert first.fulfillment_endpoint_key == DEMO_ENDPOINT_KEY
        assert second.owner_password == DEMO_ADMIN_PASSWORD
        assert second.kiosk_key == DEMO_KIOSK_KEY
        assert second.fulfillment_endpoint_key == DEMO_ENDPOINT_KEY
        assert first.product_count == len(DEMO_PRODUCTS)
        assert DEMO_ADMIN_PASSWORD not in repr(first)
        assert DEMO_KIOSK_KEY not in repr(first)
        assert DEMO_ENDPOINT_KEY not in repr(first)

        async with database.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(Tenant)) == 1
            assert await session.scalar(select(func.count()).select_from(Category)) == 3
            assert await session.scalar(select(func.count()).select_from(OptionGroup)) == 2
            assert await session.scalar(select(func.count()).select_from(Product)) == len(
                DEMO_PRODUCTS
            )
            assert await session.scalar(select(func.count()).select_from(PriceBook)) == 1
            assert (
                await session.scalar(select(func.count()).select_from(StorePriceBookAssignment))
                == 1
            )
            assert await session.scalar(select(func.count()).select_from(TaxPolicyVersion)) == 1
            tax_rate = await session.scalar(select(TaxRate))
            policy = await session.scalar(select(StoreOperatingPolicy))
            owner = await session.get(UserAccount, UUID(first.owner_user_id))
            kiosk = await session.get(KioskDevice, UUID(first.kiosk_id))
            endpoint = await session.get(
                FulfillmentEndpoint,
                UUID(first.fulfillment_endpoint_id),
            )
            catalog = await get_store_catalog(session, UUID(first.store_id), "nl-NL")
            assert tax_rate is not None and tax_rate.rate_ppm == 90_000
            assert policy is not None and policy.accepting_orders is True
            assert owner is not None and verify_password(DEMO_ADMIN_PASSWORD, owner.password_hash)
            assert kiosk is not None and verify_device_credential(
                DEMO_KIOSK_KEY, kiosk.credential_hash
            )
            assert endpoint is not None and verify_device_credential(
                DEMO_ENDPOINT_KEY, endpoint.credential_hash
            )
            assert {
                product.sku for category in catalog.categories for product in category.products
            } == {product.sku for product in DEMO_PRODUCTS}
            cappuccino = next(
                product
                for category in catalog.categories
                for product in category.products
                if product.sku == "CAPPUCCINO"
            )
            assert [group.code for group in cappuccino.option_groups] == [
                "formaat",
                "melkkeuze",
            ]
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_seed_demo_rejects_existing_drift_instead_of_mutating_it() -> None:
    database = await _database()
    try:
        async with database.session_factory() as session, session.begin():
            first = await seed_demo_store(session, _settings())
        async with database.session_factory() as session, session.begin():
            policy = await session.scalar(select(StoreOperatingPolicy))
            assert policy is not None
            policy.accepting_orders = False

        async with database.session_factory() as session, session.begin():
            with pytest.raises(ConflictError) as conflict:
                await seed_demo_store(session, _settings())
        assert conflict.value.code == "demo_seed_incomplete"

        async with database.session_factory() as session:
            policy = await session.scalar(select(StoreOperatingPolicy))
            assert policy is not None and policy.accepting_orders is False
            assert await session.get(UserAccount, UUID(first.owner_user_id)) is not None
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_seed_demo_is_forbidden_outside_development_and_test() -> None:
    database = await _database()
    try:
        settings = Settings.model_construct(
            app_env="production",
            database_url="sqlite+aiosqlite:///:memory:",
            jwt_secret="production-secret-that-is-at-least-thirty-two-bytes",
            mock_payment_enabled=False,
        )
        async with database.session_factory() as session, session.begin():
            with pytest.raises(ValueError, match="development or test"):
                await seed_demo_store(session, settings)
        async with database.session_factory() as session:
            assert await session.scalar(select(func.count()).select_from(Tenant)) == 0
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_seed_demo_failure_rolls_back_inside_a_caller_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = await _database()
    try:
        original_seed_catalog = demo_seed_module._seed_catalog

        async def fail_after_catalog(
            session: AsyncSession,
            bootstrap: BootstrapResult,
        ) -> int:
            await original_seed_catalog(session, bootstrap)
            raise RuntimeError("forced nested demo seed failure")

        monkeypatch.setattr(demo_seed_module, "_seed_catalog", fail_after_catalog)
        async with database.session_factory() as session, session.begin():
            unrelated_tenant = Tenant(code="unrelated", name="Unrelated tenant")
            session.add(unrelated_tenant)
            await session.flush()
            with pytest.raises(RuntimeError, match="forced nested demo seed failure"):
                await seed_demo_store(session, _settings())
        async with database.session_factory() as session:
            tenants = list((await session.scalars(select(Tenant).order_by(Tenant.code))).all())
            assert [tenant.code for tenant in tenants] == ["unrelated"]
    finally:
        await database.dispose()
