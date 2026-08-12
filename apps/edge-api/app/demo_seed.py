from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bootstrap import BootstrapResult, bootstrap_store
from app.core.config import Settings
from app.core.enums import PaymentProvider, PriceBookStatus
from app.core.errors import ConflictError
from app.core.security import hash_device_credential, verify_password
from app.modules.catalog.models import (
    Category,
    CategoryTranslation,
    OptionGroup,
    OptionGroupTranslation,
    OptionValue,
    OptionValueTranslation,
    PriceBook,
    PriceBookItem,
    PriceBookOptionItem,
    Product,
    ProductOptionRule,
    ProductTranslation,
    StorePriceBookAssignment,
    StoreProductAvailability,
)
from app.modules.catalog.service import get_store_catalog
from app.modules.identity.models import Role, UserAccount, UserStoreRole
from app.modules.identity.service import normalize_identifier
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
from app.modules.pricing_tax.models import TaxPolicyVersion, TaxRate

DEMO_TENANT_CODE = "demo-nl"
DEMO_ADMIN_USERNAME = "demo-owner"
DEMO_ADMIN_PASSWORD = "DemoOwner!2026-NL"
# These are public local-demo credentials, not production secrets. The environment
# boundary below is the security control; stored values are still one-way hashes.
DEMO_KIOSK_KEY = "demo-kiosk-key-development-only-2026"
DEMO_ENDPOINT_KEY = "demo-kds-key-development-only-2026"
DEMO_PRICE_BOOK_CODE = "demo-menu"
DEMO_TAX_CATEGORY = "non_alcoholic_beverage"
DEMO_VALID_FROM = datetime(2020, 1, 1, tzinfo=UTC)
EXPECTED_CATEGORY_CODES = frozenset({"koffie", "thee", "koud"})
EXPECTED_OPTION_GROUP_CODES = frozenset({"formaat", "melkkeuze"})


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    created: bool
    tenant_id: str
    store_id: str
    owner_user_id: str
    tenant_code: str
    owner_username: str
    kiosk_id: str
    fulfillment_endpoint_id: str
    product_count: int
    owner_password: str = field(default="", repr=False)
    kiosk_key: str = field(default="", repr=False)
    fulfillment_endpoint_key: str = field(default="", repr=False)

    def to_dict(self) -> dict[str, str | int | bool]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DemoProduct:
    category_code: str
    category_nl: str
    category_en: str
    sku: str
    name_nl: str
    name_en: str
    description_nl: str
    description_en: str
    price_minor: int
    sort_order: int
    allergens: tuple[str, ...] = ()
    preparation: tuple[tuple[str, str], ...] = ()
    size_options: bool = True
    milk_options: bool = False


DEMO_PRODUCTS = (
    DemoProduct(
        "koffie",
        "Koffie",
        "Coffee",
        "ESPRESSO",
        "Espresso",
        "Espresso",
        "Krachtige dubbele espresso.",
        "Rich double espresso.",
        250,
        10,
        preparation=(("recipe", "Double espresso"),),
        size_options=False,
    ),
    DemoProduct(
        "koffie",
        "Koffie",
        "Coffee",
        "CAPPUCCINO",
        "Cappuccino",
        "Cappuccino",
        "Espresso met romig melkschuim.",
        "Espresso with creamy milk foam.",
        365,
        20,
        allergens=("afhankelijk van melkkeuze: melk, soja of gluten",),
        preparation=(("recipe", "Espresso with steamed milk and foam"),),
        milk_options=True,
    ),
    DemoProduct(
        "koffie",
        "Koffie",
        "Coffee",
        "LATTE",
        "Caffe latte",
        "Caffe latte",
        "Milde espresso met warme melk.",
        "Smooth espresso with steamed milk.",
        395,
        30,
        allergens=("afhankelijk van melkkeuze: melk, soja of gluten",),
        preparation=(("recipe", "Espresso with steamed milk"),),
        milk_options=True,
    ),
    DemoProduct(
        "thee",
        "Thee",
        "Tea",
        "EARL-GREY",
        "Earl Grey thee",
        "Earl Grey tea",
        "Zwarte thee met bergamot.",
        "Black tea with bergamot.",
        295,
        40,
        preparation=(("recipe", "Steep tea for 3 minutes"),),
    ),
    DemoProduct(
        "koud",
        "Koude dranken",
        "Cold drinks",
        "ICED-LATTE",
        "Iced latte",
        "Iced latte",
        "Espresso, koude melk en ijs.",
        "Espresso, cold milk and ice.",
        425,
        50,
        allergens=("afhankelijk van melkkeuze: melk, soja of gluten",),
        preparation=(("recipe", "Espresso over ice with cold milk"),),
        milk_options=True,
    ),
    DemoProduct(
        "koud",
        "Koude dranken",
        "Cold drinks",
        "HOMEMADE-LEMONADE",
        "Huisgemaakte limonade",
        "Homemade lemonade",
        "Frisse citroenlimonade met ijs.",
        "Fresh lemon lemonade over ice.",
        350,
        60,
        preparation=(("recipe", "Serve chilled over ice"),),
    ),
)


def _require_safe_environment(settings: Settings) -> None:
    if settings.app_env not in {"development", "test"}:
        raise ValueError("demo data can only be seeded in development or test")
    if not settings.mock_payment_enabled:
        raise ValueError("demo data requires MOCK_PAYMENT_ENABLED=true")


def _uuid(value: str) -> UUID:
    return UUID(value)


async def _seed_catalog(session: AsyncSession, bootstrap: BootstrapResult) -> int:
    tenant_id = _uuid(bootstrap.tenant_id)
    store_id = _uuid(bootstrap.store_id)
    categories: dict[str, Category] = {}
    for product_spec in DEMO_PRODUCTS:
        if product_spec.category_code in categories:
            continue
        category = Category(
            tenant_id=tenant_id,
            code=product_spec.category_code,
            sort_order=len(categories) * 10,
        )
        session.add(category)
        await session.flush()
        session.add_all(
            [
                CategoryTranslation(
                    category_id=category.id,
                    locale="nl-NL",
                    name=product_spec.category_nl,
                ),
                CategoryTranslation(
                    category_id=category.id,
                    locale="en",
                    name=product_spec.category_en,
                ),
            ]
        )
        categories[product_spec.category_code] = category

    async def add_option_group(
        *,
        code: str,
        name_nl: str,
        name_en: str,
        sort_order: int,
        values: tuple[tuple[str, str, str], ...],
    ) -> tuple[OptionGroup, dict[str, OptionValue]]:
        group = OptionGroup(tenant_id=tenant_id, code=code, sort_order=sort_order)
        session.add(group)
        await session.flush()
        session.add_all(
            [
                OptionGroupTranslation(
                    option_group_id=group.id,
                    locale="nl-NL",
                    name=name_nl,
                ),
                OptionGroupTranslation(
                    option_group_id=group.id,
                    locale="en",
                    name=name_en,
                ),
            ]
        )
        created_values: dict[str, OptionValue] = {}
        for value_sort_order, (value_code, value_nl, value_en) in enumerate(
            values,
            start=1,
        ):
            value = OptionValue(
                option_group_id=group.id,
                code=value_code,
                sort_order=value_sort_order * 10,
            )
            session.add(value)
            await session.flush()
            session.add_all(
                [
                    OptionValueTranslation(
                        option_value_id=value.id,
                        locale="nl-NL",
                        name=value_nl,
                    ),
                    OptionValueTranslation(
                        option_value_id=value.id,
                        locale="en",
                        name=value_en,
                    ),
                ]
            )
            created_values[value_code] = value
        return group, created_values

    size_group, size_values = await add_option_group(
        code="formaat",
        name_nl="Formaat",
        name_en="Size",
        sort_order=10,
        values=(
            ("klein", "Klein", "Small"),
            ("normaal", "Normaal", "Regular"),
            ("groot", "Groot", "Large"),
        ),
    )
    milk_group, milk_values = await add_option_group(
        code="melkkeuze",
        name_nl="Melkkeuze",
        name_en="Milk",
        sort_order=20,
        values=(
            ("koemelk", "Koemelk", "Dairy milk"),
            ("havermelk", "Havermelk", "Oat drink"),
            ("sojadrink", "Sojadrink", "Soy drink"),
        ),
    )

    products: list[tuple[Product, DemoProduct]] = []
    for product_spec in DEMO_PRODUCTS:
        product = Product(
            tenant_id=tenant_id,
            category_id=categories[product_spec.category_code].id,
            sku=product_spec.sku,
            tax_category_code=DEMO_TAX_CATEGORY,
            preparation_data=dict(product_spec.preparation),
            allergen_data={"contains": list(product_spec.allergens)},
            sort_order=product_spec.sort_order,
        )
        session.add(product)
        await session.flush()
        session.add_all(
            [
                ProductTranslation(
                    product_id=product.id,
                    locale="nl-NL",
                    name=product_spec.name_nl,
                    description=product_spec.description_nl,
                ),
                ProductTranslation(
                    product_id=product.id,
                    locale="en",
                    name=product_spec.name_en,
                    description=product_spec.description_en,
                ),
                StoreProductAvailability(
                    store_id=store_id,
                    product_id=product.id,
                    available=True,
                ),
            ]
        )
        option_rules: list[ProductOptionRule] = []
        if product_spec.size_options:
            option_rules.append(
                ProductOptionRule(
                    product_id=product.id,
                    option_group_id=size_group.id,
                    minimum_selections=1,
                    maximum_selections=1,
                    sort_order=10,
                )
            )
        if product_spec.milk_options:
            option_rules.append(
                ProductOptionRule(
                    product_id=product.id,
                    option_group_id=milk_group.id,
                    minimum_selections=1,
                    maximum_selections=1,
                    sort_order=20,
                )
            )
        session.add_all(option_rules)
        products.append((product, product_spec))

    price_book = PriceBook(
        tenant_id=tenant_id,
        code=DEMO_PRICE_BOOK_CODE,
        version=1,
        currency="EUR",
        prices_include_tax=True,
        status=PriceBookStatus.PUBLISHED,
    )
    session.add(price_book)
    await session.flush()
    session.add(
        StorePriceBookAssignment(
            store_id=store_id,
            price_book_id=price_book.id,
            valid_from=DEMO_VALID_FROM,
        )
    )
    for product, product_spec in products:
        session.add(
            PriceBookItem(
                price_book_id=price_book.id,
                product_id=product.id,
                price_minor=product_spec.price_minor,
            )
        )
        if product_spec.size_options:
            session.add_all(
                PriceBookOptionItem(
                    price_book_id=price_book.id,
                    product_id=product.id,
                    option_value_id=value.id,
                    price_delta_minor={"klein": 0, "normaal": 50, "groot": 100}[code],
                )
                for code, value in size_values.items()
            )
        if product_spec.milk_options:
            session.add_all(
                PriceBookOptionItem(
                    price_book_id=price_book.id,
                    product_id=product.id,
                    option_value_id=value.id,
                    price_delta_minor=(50 if code in {"havermelk", "sojadrink"} else 0),
                )
                for code, value in milk_values.items()
            )

    tax_policy = TaxPolicyVersion(
        tenant_id=tenant_id,
        country_code="NL",
        version=1,
        rounding_mode="HALF_UP",
        rounding_scope="LINE",
        valid_from=DEMO_VALID_FROM,
        published=True,
    )
    session.add(tax_policy)
    await session.flush()
    session.add(
        TaxRate(
            tax_policy_version_id=tax_policy.id,
            tax_category_code=DEMO_TAX_CATEGORY,
            rate_ppm=90_000,
        )
    )
    await session.flush()
    return len(products)


async def _existing_result(session: AsyncSession) -> DemoSeedResult | None:
    tenant = await session.scalar(select(Tenant).where(Tenant.code == DEMO_TENANT_CODE))
    if tenant is None:
        return None
    legal_entity = await session.scalar(
        select(LegalEntity).where(LegalEntity.tenant_id == tenant.id)
    )
    if legal_entity is None:
        raise ConflictError("demo_seed_incomplete", "The demo tenant is incomplete")
    store = await session.scalar(select(Store).where(Store.legal_entity_id == legal_entity.id))
    owner = await session.scalar(
        select(UserAccount).where(
            UserAccount.tenant_id == tenant.id,
            UserAccount.username_normalized == normalize_identifier(DEMO_ADMIN_USERNAME),
        )
    )
    owner_role = (
        await session.scalar(
            select(UserStoreRole)
            .join(Role, Role.id == UserStoreRole.role_id)
            .where(
                UserStoreRole.user_id == owner.id,
                Role.tenant_id == tenant.id,
                Role.code == "owner",
            )
        )
        if owner is not None
        else None
    )
    kiosk = (
        await session.scalar(
            select(KioskDevice).where(
                KioskDevice.store_id == store.id,
                KioskDevice.code == "KIOSK-01",
            )
        )
        if store is not None
        else None
    )
    endpoint = None
    terminal = None
    if store is not None:
        endpoint = await session.scalar(
            select(FulfillmentEndpoint)
            .join(
                KitchenStation,
                KitchenStation.id == FulfillmentEndpoint.station_id,
            )
            .where(
                KitchenStation.store_id == store.id,
                FulfillmentEndpoint.external_reference == "KDS-01",
            )
        )
    if kiosk is not None:
        terminal = await session.scalar(
            select(PaymentTerminal).where(
                PaymentTerminal.kiosk_id == kiosk.id,
                PaymentTerminal.provider == PaymentProvider.MOCK,
            )
        )
    price_book = await session.scalar(
        select(PriceBook).where(
            PriceBook.tenant_id == tenant.id,
            PriceBook.code == DEMO_PRICE_BOOK_CODE,
            PriceBook.version == 1,
        )
    )
    policy = (
        await session.scalar(
            select(StoreOperatingPolicy).where(StoreOperatingPolicy.store_id == store.id)
        )
        if store is not None
        else None
    )
    products = list(
        (await session.scalars(select(Product).where(Product.tenant_id == tenant.id))).all()
    )
    expected_skus = {product.sku for product in DEMO_PRODUCTS}
    tax_policy = await session.scalar(
        select(TaxPolicyVersion).where(
            TaxPolicyVersion.tenant_id == tenant.id,
            TaxPolicyVersion.country_code == "NL",
            TaxPolicyVersion.version == 1,
            TaxPolicyVersion.published,
        )
    )
    tax_rate = (
        await session.get(TaxRate, (tax_policy.id, DEMO_TAX_CATEGORY))
        if tax_policy is not None
        else None
    )
    expected_price_by_sku = {product.sku: product.price_minor for product in DEMO_PRODUCTS}
    price_items = (
        list(
            (
                await session.scalars(
                    select(PriceBookItem).where(PriceBookItem.price_book_id == price_book.id)
                )
            ).all()
        )
        if price_book is not None
        else []
    )
    option_groups = list(
        (await session.scalars(select(OptionGroup).where(OptionGroup.tenant_id == tenant.id))).all()
    )
    categories = list(
        (await session.scalars(select(Category).where(Category.tenant_id == tenant.id))).all()
    )
    assignment = (
        await session.scalar(
            select(StorePriceBookAssignment).where(
                StorePriceBookAssignment.store_id == store.id,
                StorePriceBookAssignment.price_book_id == price_book.id,
            )
        )
        if store is not None and price_book is not None
        else None
    )
    catalog = (
        await get_store_catalog(session, store.id, "nl-NL")
        if store is not None and price_book is not None and assignment is not None
        else None
    )
    catalog_products = (
        [product for category in catalog.categories for product in category.products]
        if catalog is not None
        else []
    )
    if (
        store is None
        or owner is None
        or owner_role is None
        or kiosk is None
        or endpoint is None
        or terminal is None
        or price_book is None
        or tax_policy is None
        or policy is None
        or {product.sku for product in products} != expected_skus
        or {product.sku for product in catalog_products} != expected_skus
        or assignment is None
        or tax_rate is None
        or tax_rate.rate_ppm != 90_000
        or len(price_items) != len(DEMO_PRODUCTS)
        or {
            product.sku: item.price_minor
            for item in price_items
            for product in products
            if product.id == item.product_id
        }
        != expected_price_by_sku
        or {category.code for category in categories} != EXPECTED_CATEGORY_CODES
        or {group.code for group in option_groups} != EXPECTED_OPTION_GROUP_CODES
        or not policy.accepting_orders
        or not tenant.active
        or not legal_entity.active
        or not store.active
        or not owner.active
        or not kiosk.active
        or not endpoint.active
        or not terminal.active
        or price_book.status != PriceBookStatus.PUBLISHED
        or not tax_policy.published
        or kiosk.credential_hash != hash_device_credential(DEMO_KIOSK_KEY)
        or endpoint.credential_hash != hash_device_credential(DEMO_ENDPOINT_KEY)
        or not verify_password(DEMO_ADMIN_PASSWORD, owner.password_hash)
    ):
        raise ConflictError(
            "demo_seed_incomplete",
            "Existing demo data differs from the expected safe demo dataset",
        )
    return DemoSeedResult(
        created=False,
        tenant_id=str(tenant.id),
        store_id=str(store.id),
        owner_user_id=str(owner.id),
        tenant_code=DEMO_TENANT_CODE,
        owner_username=DEMO_ADMIN_USERNAME,
        kiosk_id=str(kiosk.id),
        fulfillment_endpoint_id=str(endpoint.id),
        product_count=len(products),
        owner_password=DEMO_ADMIN_PASSWORD,
        kiosk_key=DEMO_KIOSK_KEY,
        fulfillment_endpoint_key=DEMO_ENDPOINT_KEY,
    )


async def seed_demo_store(session: AsyncSession, settings: Settings) -> DemoSeedResult:
    """Create or strictly verify the fixed local demo dataset.

    The public credentials below are intentionally deterministic so a first-time local
    operator can configure all three frontends. They are never accepted outside the
    explicitly permitted development/test environments.
    """

    _require_safe_environment(settings)
    bootstrap: BootstrapResult | None = None
    product_count = 0
    async with session.begin_nested():
        # The savepoint removes every partially-created row without rolling back
        # unrelated work owned by a caller's surrounding transaction.
        existing = await _existing_result(session)
        if existing is not None:
            return existing

        bootstrap = await bootstrap_store(
            session,
            settings,
            tenant_code=DEMO_TENANT_CODE,
            tenant_name="Demo Dranken Nederland",
            legal_entity_code="demo-dranken-bv",
            legal_entity_name="Demo Dranken Nederland B.V.",
            store_code="AMS-DEMO",
            store_name="Amsterdam Demo Bar",
            owner_username=DEMO_ADMIN_USERNAME,
            owner_display_name="Demo Store Owner",
            owner_password=DEMO_ADMIN_PASSWORD,
        )
        store_id = _uuid(bootstrap.store_id)
        policy = await session.scalar(
            select(StoreOperatingPolicy).where(StoreOperatingPolicy.store_id == store_id)
        )
        kiosk = await session.get(KioskDevice, _uuid(bootstrap.kiosk_id))
        endpoint = await session.get(
            FulfillmentEndpoint,
            _uuid(bootstrap.fulfillment_endpoint_id),
        )
        owner = await session.get(UserAccount, _uuid(bootstrap.owner_user_id))
        if policy is None or kiosk is None or endpoint is None or owner is None:
            raise RuntimeError("bootstrap did not create the required demo resources")
        policy.accepting_orders = True
        kiosk.credential_hash = hash_device_credential(DEMO_KIOSK_KEY)
        endpoint.credential_hash = hash_device_credential(DEMO_ENDPOINT_KEY)
        product_count = await _seed_catalog(session, bootstrap)
        await session.flush()
    if bootstrap is None:
        raise RuntimeError("demo bootstrap did not return a result")
    return DemoSeedResult(
        created=True,
        tenant_id=bootstrap.tenant_id,
        store_id=bootstrap.store_id,
        owner_user_id=bootstrap.owner_user_id,
        tenant_code=DEMO_TENANT_CODE,
        owner_username=DEMO_ADMIN_USERNAME,
        owner_password=DEMO_ADMIN_PASSWORD,
        kiosk_id=bootstrap.kiosk_id,
        kiosk_key=DEMO_KIOSK_KEY,
        fulfillment_endpoint_id=bootstrap.fulfillment_endpoint_id,
        fulfillment_endpoint_key=DEMO_ENDPOINT_KEY,
        product_count=product_count,
    )
