from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import and_, or_, select, true, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, PriceBookStatus
from app.core.errors import ConflictError, NotFoundError
from app.core.principals import Principal
from app.modules.audit.service import add_audit_log
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
from app.modules.catalog.schemas import (
    CatalogCategoryResponse,
    CatalogOptionGroupResponse,
    CatalogOptionValueResponse,
    CatalogProductResponse,
    CreateCategoryRequest,
    CreateOptionGroupRequest,
    CreatePriceBookRequest,
    CreateProductRequest,
    StoreCatalogResponse,
)
from app.modules.organization.models import LegalEntity, Store
from app.modules.organization.service import get_store_for_tenant
from app.persistence.base import utc_now


def normalize_code(value: str) -> str:
    return value.strip().lower()


def _audit_catalog_change(
    session: AsyncSession,
    principal: Principal,
    *,
    store_id: UUID,
    action: str,
    target_type: str,
    target_id: UUID,
    before: dict[str, object] | None = None,
    after: dict[str, object] | None = None,
) -> None:
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=store_id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before=before,
        after=after,
    )


def _localized_value(
    values: dict[tuple[UUID, str], str],
    entity_id: UUID,
    requested_locale: str,
    store_locale: str,
    fallback: str,
) -> str:
    for locale in (requested_locale, store_locale, "en"):
        value = values.get((entity_id, locale))
        if value:
            return value
    return fallback


async def create_category(
    session: AsyncSession,
    principal: Principal,
    request: CreateCategoryRequest,
) -> Category:
    await get_store_for_tenant(session, principal, request.store_id)
    category = Category(
        tenant_id=principal.tenant_id,
        code=normalize_code(request.code),
        sort_order=request.sort_order,
    )
    session.add(category)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("category_exists", "The category code already exists") from exc
    session.add_all(
        CategoryTranslation(category_id=category.id, locale=locale, name=name.strip())
        for locale, name in request.translations.items()
    )
    await session.flush()
    _audit_catalog_change(
        session,
        principal,
        store_id=request.store_id,
        action="catalog.category.created",
        target_type="category",
        target_id=category.id,
        after={"code": category.code, "active": category.active},
    )
    return category


async def create_option_group(
    session: AsyncSession,
    principal: Principal,
    request: CreateOptionGroupRequest,
) -> OptionGroup:
    await get_store_for_tenant(session, principal, request.store_id)
    if len({normalize_code(value.code) for value in request.values}) != len(request.values):
        raise ConflictError("duplicate_option_code", "Option value codes must be distinct")
    group = OptionGroup(
        tenant_id=principal.tenant_id,
        code=normalize_code(request.code),
        sort_order=request.sort_order,
    )
    session.add(group)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("option_group_exists", "The option group code already exists") from exc
    session.add_all(
        OptionGroupTranslation(option_group_id=group.id, locale=locale, name=name.strip())
        for locale, name in request.translations.items()
    )
    for value_input in request.values:
        value = OptionValue(
            option_group_id=group.id,
            code=normalize_code(value_input.code),
            sort_order=value_input.sort_order,
        )
        session.add(value)
        await session.flush()
        session.add_all(
            OptionValueTranslation(option_value_id=value.id, locale=locale, name=name.strip())
            for locale, name in value_input.translations.items()
        )
    await session.flush()
    _audit_catalog_change(
        session,
        principal,
        store_id=request.store_id,
        action="catalog.option_group.created",
        target_type="option_group",
        target_id=group.id,
        after={"code": group.code, "active": group.active},
    )
    return group


async def create_product(
    session: AsyncSession,
    principal: Principal,
    request: CreateProductRequest,
) -> Product:
    await get_store_for_tenant(session, principal, request.store_id)
    category = await session.scalar(
        select(Category).where(
            Category.id == request.category_id,
            Category.tenant_id == principal.tenant_id,
            Category.active,
        )
    )
    if category is None:
        raise NotFoundError("category", str(request.category_id))
    requested_groups = {rule.option_group_id for rule in request.option_rules}
    groups = set(
        (
            await session.scalars(
                select(OptionGroup.id).where(
                    OptionGroup.id.in_(requested_groups),
                    OptionGroup.tenant_id == principal.tenant_id,
                    OptionGroup.active,
                )
            )
        ).all()
    )
    if groups != requested_groups:
        raise ConflictError("invalid_option_group", "One or more option groups are invalid")
    product = Product(
        tenant_id=principal.tenant_id,
        category_id=category.id,
        sku=request.sku.strip().upper(),
        tax_category_code=normalize_code(request.tax_category_code),
        image_url=str(request.image_url) if request.image_url else None,
        preparation_data=request.preparation_data,
        allergen_data=request.allergen_data,
        sort_order=request.sort_order,
    )
    session.add(product)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("product_exists", "The product SKU already exists") from exc
    session.add_all(
        ProductTranslation(
            product_id=product.id,
            locale=locale,
            name=translation.name.strip(),
            description=translation.description.strip(),
        )
        for locale, translation in request.translations.items()
    )
    session.add_all(
        ProductOptionRule(
            product_id=product.id,
            option_group_id=rule.option_group_id,
            minimum_selections=rule.minimum_selections,
            maximum_selections=rule.maximum_selections,
            sort_order=rule.sort_order,
        )
        for rule in request.option_rules
    )
    session.add(
        StoreProductAvailability(
            store_id=request.store_id,
            product_id=product.id,
            available=True,
        )
    )
    await session.flush()
    _audit_catalog_change(
        session,
        principal,
        store_id=request.store_id,
        action="catalog.product.created",
        target_type="product",
        target_id=product.id,
        after={
            "sku": product.sku,
            "tax_category_code": product.tax_category_code,
            "active": product.active,
        },
    )
    return product


async def set_product_availability(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    product_id: UUID,
    *,
    available: bool,
    expected_version: int,
) -> StoreProductAvailability:
    await get_store_for_tenant(session, principal, store_id)
    availability = await session.scalar(
        select(StoreProductAvailability).where(
            StoreProductAvailability.store_id == store_id,
            StoreProductAvailability.product_id == product_id,
        )
    )
    if availability is None:
        raise NotFoundError("store_product_availability", str(product_id))
    if availability.version != expected_version:
        raise ConflictError("stale_version", "Product availability was modified by another request")
    previous_available = availability.available
    previous_version = availability.version
    availability = await session.scalar(
        update(StoreProductAvailability)
        .where(
            StoreProductAvailability.store_id == store_id,
            StoreProductAvailability.product_id == product_id,
            StoreProductAvailability.version == expected_version,
        )
        .values(available=available, version=expected_version + 1)
        .returning(StoreProductAvailability)
        .execution_options(populate_existing=True)
    )
    if availability is None:
        raise ConflictError("stale_version", "Product availability was modified by another request")
    _audit_catalog_change(
        session,
        principal,
        store_id=store_id,
        action="catalog.product_availability.changed",
        target_type="product",
        target_id=availability.product_id,
        before={"available": previous_available, "version": previous_version},
        after={"available": availability.available, "version": availability.version},
    )
    return cast(StoreProductAvailability, availability)


async def create_price_book(
    session: AsyncSession,
    principal: Principal,
    request: CreatePriceBookRequest,
) -> PriceBook:
    store = await get_store_for_tenant(session, principal, request.store_id)
    await session.scalar(select(Store.id).where(Store.id == store.id).with_for_update())
    if request.currency.upper() != store.currency:
        raise ConflictError("currency_mismatch", "The price book currency must match the store")
    if request.valid_to is not None and request.valid_to <= request.valid_from:
        raise ConflictError("invalid_validity", "valid_to must be after valid_from")
    overlap = await session.scalar(
        select(StorePriceBookAssignment.id).where(
            StorePriceBookAssignment.store_id == store.id,
            or_(
                StorePriceBookAssignment.valid_to.is_(None),
                StorePriceBookAssignment.valid_to > request.valid_from,
            ),
            (
                true()
                if request.valid_to is None
                else StorePriceBookAssignment.valid_from < request.valid_to
            ),
        )
    )
    if overlap is not None:
        raise ConflictError("price_book_overlap", "A price book is already active in this interval")
    product_ids = {item.product_id for item in request.items}
    valid_products = set(
        (
            await session.scalars(
                select(Product.id).where(
                    Product.id.in_(product_ids),
                    Product.tenant_id == principal.tenant_id,
                    Product.active,
                )
            )
        ).all()
    )
    if valid_products != product_ids:
        raise ConflictError("invalid_product", "One or more products are invalid")
    requested_option_pairs = {
        (item.product_id, option.option_value_id)
        for item in request.items
        for option in item.option_prices
    }
    if requested_option_pairs:
        valid_option_pairs = set(
            (
                await session.execute(
                    select(ProductOptionRule.product_id, OptionValue.id)
                    .join(
                        OptionValue,
                        OptionValue.option_group_id == ProductOptionRule.option_group_id,
                    )
                    .join(OptionGroup, OptionGroup.id == ProductOptionRule.option_group_id)
                    .where(
                        ProductOptionRule.product_id.in_(product_ids),
                        OptionValue.id.in_(
                            option_value_id for _, option_value_id in requested_option_pairs
                        ),
                        OptionValue.active,
                        OptionGroup.active,
                    )
                )
            ).all()
        )
        if valid_option_pairs != requested_option_pairs:
            raise ConflictError(
                "invalid_option_price",
                "Every option price must reference an active option allowed by that product",
            )
    price_book = PriceBook(
        tenant_id=principal.tenant_id,
        code=normalize_code(request.code),
        version=request.version,
        currency=request.currency.upper(),
        prices_include_tax=request.prices_include_tax,
        status=PriceBookStatus.PUBLISHED,
    )
    session.add(price_book)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("price_book_exists", "The price book version already exists") from exc
    session.add(
        StorePriceBookAssignment(
            store_id=store.id,
            price_book_id=price_book.id,
            valid_from=request.valid_from,
            valid_to=request.valid_to,
        )
    )
    for item in request.items:
        session.add(
            PriceBookItem(
                price_book_id=price_book.id,
                product_id=item.product_id,
                price_minor=item.price_minor,
            )
        )
        session.add_all(
            PriceBookOptionItem(
                price_book_id=price_book.id,
                product_id=item.product_id,
                option_value_id=option.option_value_id,
                price_delta_minor=option.price_delta_minor,
            )
            for option in item.option_prices
        )
    await session.flush()
    _audit_catalog_change(
        session,
        principal,
        store_id=store.id,
        action="pricing.price_book.created",
        target_type="price_book",
        target_id=price_book.id,
        after={
            "code": price_book.code,
            "version": price_book.version,
            "currency": price_book.currency,
            "prices_include_tax": price_book.prices_include_tax,
        },
    )
    return price_book


async def get_current_price_book(
    session: AsyncSession,
    store_id: UUID,
    *,
    at: datetime | None = None,
) -> PriceBook:
    effective_at = at or utc_now()
    price_book = await session.scalar(
        select(PriceBook)
        .join(StorePriceBookAssignment, StorePriceBookAssignment.price_book_id == PriceBook.id)
        .where(
            StorePriceBookAssignment.store_id == store_id,
            StorePriceBookAssignment.valid_from <= effective_at,
            or_(
                StorePriceBookAssignment.valid_to.is_(None),
                StorePriceBookAssignment.valid_to > effective_at,
            ),
            PriceBook.status == PriceBookStatus.PUBLISHED,
        )
        .order_by(StorePriceBookAssignment.valid_from.desc())
    )
    if price_book is None:
        raise ConflictError("price_book_unavailable", "No published price book is active")
    return price_book


async def get_store_catalog(
    session: AsyncSession,
    store_id: UUID,
    requested_locale: str,
) -> StoreCatalogResponse:
    store_row = (
        await session.execute(
            select(Store, LegalEntity)
            .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
            .where(Store.id == store_id, Store.active, LegalEntity.active)
        )
    ).one_or_none()
    if store_row is None:
        raise NotFoundError("store", str(store_id))
    store, legal_entity = store_row
    price_book = await get_current_price_book(session, store_id)

    product_rows = (
        await session.execute(
            select(Product, PriceBookItem)
            .join(
                StoreProductAvailability,
                and_(
                    StoreProductAvailability.product_id == Product.id,
                    StoreProductAvailability.store_id == store_id,
                    StoreProductAvailability.available,
                ),
            )
            .join(
                PriceBookItem,
                and_(
                    PriceBookItem.product_id == Product.id,
                    PriceBookItem.price_book_id == price_book.id,
                ),
            )
            .where(Product.tenant_id == legal_entity.tenant_id, Product.active)
            .order_by(Product.sort_order, Product.sku)
        )
    ).all()
    product_ids = {product.id for product, _ in product_rows}
    category_ids = {product.category_id for product, _ in product_rows}
    categories = list(
        (
            await session.scalars(
                select(Category)
                .where(Category.id.in_(category_ids), Category.active)
                .order_by(Category.sort_order, Category.code)
            )
        ).all()
    )
    locales = {requested_locale, store.locale, "en"}
    category_names = {
        (row.category_id, row.locale): row.name
        for row in (
            await session.scalars(
                select(CategoryTranslation).where(
                    CategoryTranslation.category_id.in_(category_ids),
                    CategoryTranslation.locale.in_(locales),
                )
            )
        ).all()
    }
    product_translations = {
        (row.product_id, row.locale): row
        for row in (
            await session.scalars(
                select(ProductTranslation).where(
                    ProductTranslation.product_id.in_(product_ids),
                    ProductTranslation.locale.in_(locales),
                )
            )
        ).all()
    }
    rules = list(
        (
            await session.scalars(
                select(ProductOptionRule)
                .where(ProductOptionRule.product_id.in_(product_ids))
                .order_by(ProductOptionRule.sort_order)
            )
        ).all()
    )
    group_ids = {rule.option_group_id for rule in rules}
    groups = {
        group.id: group
        for group in (
            await session.scalars(
                select(OptionGroup).where(OptionGroup.id.in_(group_ids), OptionGroup.active)
            )
        ).all()
    }
    group_names = {
        (row.option_group_id, row.locale): row.name
        for row in (
            await session.scalars(
                select(OptionGroupTranslation).where(
                    OptionGroupTranslation.option_group_id.in_(group_ids),
                    OptionGroupTranslation.locale.in_(locales),
                )
            )
        ).all()
    }
    values = list(
        (
            await session.scalars(
                select(OptionValue)
                .where(OptionValue.option_group_id.in_(group_ids), OptionValue.active)
                .order_by(OptionValue.sort_order, OptionValue.code)
            )
        ).all()
    )
    value_ids = {value.id for value in values}
    value_names = {
        (row.option_value_id, row.locale): row.name
        for row in (
            await session.scalars(
                select(OptionValueTranslation).where(
                    OptionValueTranslation.option_value_id.in_(value_ids),
                    OptionValueTranslation.locale.in_(locales),
                )
            )
        ).all()
    }
    option_prices = {
        (row.product_id, row.option_value_id): row.price_delta_minor
        for row in (
            await session.scalars(
                select(PriceBookOptionItem).where(
                    PriceBookOptionItem.price_book_id == price_book.id,
                    PriceBookOptionItem.product_id.in_(product_ids),
                )
            )
        ).all()
    }
    values_by_group: dict[UUID, list[OptionValue]] = defaultdict(list)
    for value in values:
        values_by_group[value.option_group_id].append(value)
    rules_by_product: dict[UUID, list[ProductOptionRule]] = defaultdict(list)
    for rule in rules:
        rules_by_product[rule.product_id].append(rule)

    product_responses: dict[UUID, CatalogProductResponse] = {}
    for product, price_item in product_rows:
        translation = next(
            (
                product_translations.get((product.id, locale))
                for locale in (requested_locale, store.locale, "en")
                if product_translations.get((product.id, locale)) is not None
            ),
            None,
        )
        product_name = translation.name if translation else product.sku
        product_description = translation.description if translation else ""
        option_groups: list[CatalogOptionGroupResponse] = []
        for rule in rules_by_product.get(product.id, []):
            group = groups.get(rule.option_group_id)
            if group is None:
                continue
            option_groups.append(
                CatalogOptionGroupResponse(
                    id=group.id,
                    code=group.code,
                    name=_localized_value(
                        group_names,
                        group.id,
                        requested_locale,
                        store.locale,
                        group.code,
                    ),
                    minimum_selections=rule.minimum_selections,
                    maximum_selections=rule.maximum_selections,
                    values=[
                        CatalogOptionValueResponse(
                            id=value.id,
                            code=value.code,
                            name=_localized_value(
                                value_names,
                                value.id,
                                requested_locale,
                                store.locale,
                                value.code,
                            ),
                            price_delta_minor=option_prices.get((product.id, value.id), 0),
                        )
                        for value in values_by_group.get(group.id, [])
                    ],
                )
            )
        product_responses[product.id] = CatalogProductResponse(
            id=product.id,
            sku=product.sku,
            name=product_name,
            description=product_description,
            image_url=product.image_url,
            price_minor=price_item.price_minor,
            currency=price_book.currency,
            tax_category_code=product.tax_category_code,
            allergen_data=product.allergen_data,
            option_groups=option_groups,
        )
    products_by_category: dict[UUID, list[CatalogProductResponse]] = defaultdict(list)
    for product, _ in product_rows:
        products_by_category[product.category_id].append(product_responses[product.id])
    return StoreCatalogResponse(
        store_id=store.id,
        locale=requested_locale,
        currency=price_book.currency,
        price_book_id=price_book.id,
        categories=[
            CatalogCategoryResponse(
                id=category.id,
                code=category.code,
                name=_localized_value(
                    category_names,
                    category.id,
                    requested_locale,
                    store.locale,
                    category.code,
                ),
                products=products_by_category.get(category.id, []),
            )
            for category in categories
        ],
    )
