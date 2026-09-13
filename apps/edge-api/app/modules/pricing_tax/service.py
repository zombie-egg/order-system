from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select, true
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import ActorType, FulfillmentType, PromotionType, QuoteStatus
from app.core.errors import ConflictError, NotFoundError
from app.core.principals import Principal
from app.modules.audit.service import add_audit_log
from app.modules.catalog.models import (
    OptionGroup,
    OptionGroupTranslation,
    OptionValue,
    OptionValueTranslation,
    PriceBookItem,
    PriceBookOptionItem,
    Product,
    ProductOptionRule,
    ProductTranslation,
    StoreProductAvailability,
)
from app.modules.catalog.service import get_current_price_book, normalize_code
from app.modules.organization.models import (
    KioskDevice,
    LegalEntity,
    Store,
    StoreOperatingPolicy,
    Tenant,
)
from app.modules.organization.service import get_store_for_tenant
from app.modules.pricing_tax.models import (
    PriceQuote,
    PriceQuoteDiscountLine,
    PriceQuoteItem,
    PriceQuoteItemOption,
    PriceQuoteTaxLine,
    Promotion,
    TaxPolicyVersion,
    TaxRate,
)
from app.modules.pricing_tax.schemas import (
    CreatePromotionRequest,
    CreateQuoteRequest,
    CreateTaxPolicyRequest,
    QuoteItemResponse,
    QuoteOptionResponse,
    QuoteResponse,
    QuoteTaxLineResponse,
)
from app.persistence.base import utc_now


@dataclass(slots=True)
class CalculatedOption:
    group_id: UUID
    value_id: UUID
    group_code: str
    group_name: str
    value_code: str
    value_name: str
    price_delta_minor: int


@dataclass(slots=True)
class CalculatedLine:
    line_number: int
    product: Product
    name: str
    quantity: int
    unit_price_minor: int
    options: list[CalculatedOption]
    base_minor: int
    discount_minor: int
    tax_rate_ppm: int
    net_minor: int
    tax_minor: int
    total_minor: int


def _round_half_up(numerator: int, denominator: int) -> int:
    if numerator < 0 or denominator <= 0:
        raise ValueError("Rounding only supports non-negative values and a positive denominator")
    return (numerator + denominator // 2) // denominator


def _request_hash(request: CreateQuoteRequest) -> str:
    payload = {
        "items": [
            {
                "product_id": str(item.product_id),
                "quantity": item.quantity,
                "option_value_ids": sorted(str(value_id) for value_id in item.option_value_ids),
            }
            for item in request.items
        ],
        "locale": request.locale,
        "promotion_code": normalize_code(request.promotion_code)
        if request.promotion_code
        else None,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _allocate_discount(total_discount: int, bases: list[int]) -> list[int]:
    if total_discount == 0:
        return [0] * len(bases)
    subtotal = sum(bases)
    if subtotal <= 0 or total_discount > subtotal:
        raise ConflictError("invalid_discount", "The discount cannot exceed the quote subtotal")
    allocated = [(total_discount * base) // subtotal for base in bases]
    remainder = total_discount - sum(allocated)
    ranking = sorted(
        range(len(bases)),
        key=lambda index: ((total_discount * bases[index]) % subtotal, -index),
        reverse=True,
    )
    for index in ranking[:remainder]:
        allocated[index] += 1
    return allocated


async def create_tax_policy(
    session: AsyncSession,
    principal: Principal,
    store: Store,
    request: CreateTaxPolicyRequest,
) -> TaxPolicyVersion:
    authorized_store = await get_store_for_tenant(session, principal, request.store_id)
    if authorized_store.id != store.id:
        raise ConflictError(
            "tax_policy_store_mismatch",
            "The tax policy store does not match the authorized store",
        )
    store = authorized_store
    await session.scalar(
        select(Tenant.id).where(Tenant.id == principal.tenant_id).with_for_update()
    )
    if request.valid_to is not None and request.valid_to <= request.valid_from:
        raise ConflictError("invalid_validity", "valid_to must be after valid_from")
    overlap = await session.scalar(
        select(TaxPolicyVersion.id).where(
            TaxPolicyVersion.tenant_id == principal.tenant_id,
            TaxPolicyVersion.country_code == store.country_code,
            TaxPolicyVersion.published,
            or_(
                TaxPolicyVersion.valid_to.is_(None), TaxPolicyVersion.valid_to > request.valid_from
            ),
            (
                true()
                if request.valid_to is None
                else TaxPolicyVersion.valid_from < request.valid_to
            ),
        )
    )
    if overlap is not None:
        raise ConflictError("tax_policy_overlap", "A tax policy is already active in this interval")
    if len({normalize_code(rate.tax_category_code) for rate in request.rates}) != len(
        request.rates
    ):
        raise ConflictError("duplicate_tax_rate", "Tax category codes must be distinct")
    policy = TaxPolicyVersion(
        tenant_id=principal.tenant_id,
        country_code=store.country_code,
        version=request.version,
        rounding_mode=request.rounding_mode,
        rounding_scope=request.rounding_scope,
        valid_from=request.valid_from,
        valid_to=request.valid_to,
        published=True,
    )
    session.add(policy)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("tax_policy_exists", "The tax policy version already exists") from exc
    session.add_all(
        TaxRate(
            tax_policy_version_id=policy.id,
            tax_category_code=normalize_code(rate.tax_category_code),
            rate_ppm=rate.rate_ppm,
        )
        for rate in request.rates
    )
    await session.flush()
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=store.id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="pricing.tax_policy.created",
        target_type="tax_policy_version",
        target_id=policy.id,
        after={
            "country_code": policy.country_code,
            "version": policy.version,
            "rounding_mode": policy.rounding_mode,
            "rounding_scope": policy.rounding_scope,
        },
    )
    return policy


async def create_promotion(
    session: AsyncSession,
    principal: Principal,
    request: CreatePromotionRequest,
) -> Promotion:
    await get_store_for_tenant(session, principal, request.store_id)
    if request.ends_at is not None and request.ends_at <= request.starts_at:
        raise ConflictError("invalid_validity", "ends_at must be after starts_at")
    if request.promotion_type == PromotionType.PERCENTAGE and request.value > 1_000_000:
        raise ConflictError("invalid_percentage", "Percentage promotion value cannot exceed 100%")
    promotion = Promotion(
        store_id=request.store_id,
        code=normalize_code(request.code),
        name=request.name.strip(),
        promotion_type=request.promotion_type,
        value=request.value,
        minimum_total_minor=request.minimum_total_minor,
        starts_at=request.starts_at,
        ends_at=request.ends_at,
    )
    session.add(promotion)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise ConflictError("promotion_exists", "The promotion code already exists") from exc
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=request.store_id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="pricing.promotion.created",
        target_type="promotion",
        target_id=promotion.id,
        after={
            "code": promotion.code,
            "promotion_type": promotion.promotion_type.value,
            "value": promotion.value,
        },
    )
    return promotion


async def _current_tax_policy(
    session: AsyncSession,
    tenant_id: UUID,
    country_code: str,
) -> tuple[TaxPolicyVersion, dict[str, int]]:
    now = utc_now()
    policy = await session.scalar(
        select(TaxPolicyVersion)
        .where(
            TaxPolicyVersion.tenant_id == tenant_id,
            TaxPolicyVersion.country_code == country_code,
            TaxPolicyVersion.published,
            TaxPolicyVersion.valid_from <= now,
            or_(TaxPolicyVersion.valid_to.is_(None), TaxPolicyVersion.valid_to > now),
        )
        .order_by(TaxPolicyVersion.valid_from.desc())
    )
    if policy is None:
        raise ConflictError("tax_policy_unavailable", "No published tax policy is active")
    rates = {
        rate.tax_category_code: rate.rate_ppm
        for rate in (
            await session.scalars(select(TaxRate).where(TaxRate.tax_policy_version_id == policy.id))
        ).all()
    }
    return policy, rates


async def _translation(
    session: AsyncSession,
    model: type[Any],
    id_column: Any,
    entity_id: UUID,
    requested_locale: str,
    store_locale: str,
) -> Any | None:
    translations = list(
        (
            await session.scalars(
                select(model).where(
                    id_column == entity_id,
                    model.locale.in_({requested_locale, store_locale, "en"}),
                )
            )
        ).all()
    )
    by_locale = {translation.locale: translation for translation in translations}
    return next(
        (
            by_locale[locale]
            for locale in (requested_locale, store_locale, "en")
            if locale in by_locale
        ),
        None,
    )


async def _calculate_line(
    session: AsyncSession,
    *,
    line_number: int,
    store: Store,
    tenant_id: UUID,
    price_book_id: UUID,
    prices_include_tax: bool,
    locale: str,
    product_id: UUID,
    quantity: int,
    selected_value_ids: list[UUID],
    tax_rates: dict[str, int],
) -> CalculatedLine:
    if len(set(selected_value_ids)) != len(selected_value_ids):
        raise ConflictError("duplicate_option", "An option value cannot be selected twice")
    product = await session.scalar(
        select(Product)
        .join(
            StoreProductAvailability,
            and_(
                StoreProductAvailability.product_id == Product.id,
                StoreProductAvailability.store_id == store.id,
                StoreProductAvailability.available,
            ),
        )
        .where(Product.id == product_id, Product.tenant_id == tenant_id, Product.active)
    )
    if product is None:
        raise NotFoundError("available_product", str(product_id))
    price_item = await session.scalar(
        select(PriceBookItem).where(
            PriceBookItem.price_book_id == price_book_id,
            PriceBookItem.product_id == product.id,
        )
    )
    if price_item is None:
        raise ConflictError("product_not_priced", f"Product {product.sku} has no active price")
    product_translation = await _translation(
        session,
        ProductTranslation,
        ProductTranslation.product_id,
        product.id,
        locale,
        store.locale,
    )
    product_name = product_translation.name if product_translation else product.sku
    rules = list(
        (
            await session.scalars(
                select(ProductOptionRule)
                .join(OptionGroup, OptionGroup.id == ProductOptionRule.option_group_id)
                .where(
                    ProductOptionRule.product_id == product.id,
                    OptionGroup.store_id == store.id,
                    OptionGroup.active,
                )
            )
        ).all()
    )
    rules_by_group = {rule.option_group_id: rule for rule in rules}
    selected_values = list(
        (
            await session.scalars(
                select(OptionValue).where(
                    OptionValue.id.in_(selected_value_ids), OptionValue.active
                )
            )
        ).all()
    )
    if len(selected_values) != len(selected_value_ids):
        raise ConflictError("invalid_option", "One or more selected option values are invalid")
    counts = Counter(value.option_group_id for value in selected_values)
    if any(group_id not in rules_by_group for group_id in counts):
        raise ConflictError("option_not_allowed", "An option is not allowed for this product")
    for group_id, rule in rules_by_group.items():
        count = counts.get(group_id, 0)
        if count < rule.minimum_selections or count > rule.maximum_selections:
            raise ConflictError(
                "option_selection_invalid",
                "The selected options do not satisfy the product rules",
                details={"option_group_id": str(group_id), "selected": count},
            )
    groups = {
        group.id: group
        for group in (
            await session.scalars(
                select(OptionGroup).where(
                    OptionGroup.id.in_(counts),
                    OptionGroup.store_id == store.id,
                    OptionGroup.active,
                )
            )
        ).all()
    }
    if set(groups) != set(counts):
        raise ConflictError(
            "option_group_unavailable",
            "One or more selected option groups are inactive or unavailable",
        )
    option_prices = {
        row.option_value_id: row.price_delta_minor
        for row in (
            await session.scalars(
                select(PriceBookOptionItem).where(
                    PriceBookOptionItem.price_book_id == price_book_id,
                    PriceBookOptionItem.product_id == product.id,
                    PriceBookOptionItem.option_value_id.in_(selected_value_ids),
                )
            )
        ).all()
    }
    calculated_options: list[CalculatedOption] = []
    for value in sorted(
        selected_values, key=lambda item: (str(item.option_group_id), item.sort_order)
    ):
        group = groups[value.option_group_id]
        group_translation = await _translation(
            session,
            OptionGroupTranslation,
            OptionGroupTranslation.option_group_id,
            group.id,
            locale,
            store.locale,
        )
        value_translation = await _translation(
            session,
            OptionValueTranslation,
            OptionValueTranslation.option_value_id,
            value.id,
            locale,
            store.locale,
        )
        calculated_options.append(
            CalculatedOption(
                group_id=group.id,
                value_id=value.id,
                group_code=group.code,
                group_name=group_translation.name if group_translation else group.code,
                value_code=value.code,
                value_name=value_translation.name if value_translation else value.code,
                price_delta_minor=option_prices.get(value.id, 0),
            )
        )
    per_unit = price_item.price_minor + sum(
        option.price_delta_minor for option in calculated_options
    )
    if per_unit < 0:
        raise ConflictError(
            "negative_line_price", "Option adjustments made the line price negative"
        )
    tax_rate = tax_rates.get(product.tax_category_code)
    if tax_rate is None:
        raise ConflictError(
            "tax_rate_missing", f"No active tax rate exists for {product.tax_category_code}"
        )
    return CalculatedLine(
        line_number=line_number,
        product=product,
        name=product_name,
        quantity=quantity,
        unit_price_minor=price_item.price_minor,
        options=calculated_options,
        base_minor=per_unit * quantity,
        discount_minor=0,
        tax_rate_ppm=tax_rate,
        net_minor=0,
        tax_minor=0,
        total_minor=0,
    )


async def create_quote(
    session: AsyncSession,
    settings: Settings,
    *,
    store_id: UUID,
    kiosk_id: UUID,
    request: CreateQuoteRequest,
) -> QuoteResponse:
    now = utc_now()
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
    if not policy.accepting_orders:
        raise ConflictError("store_not_accepting_orders", "The store is not accepting orders")
    kiosk = await session.scalar(
        select(KioskDevice).where(
            KioskDevice.id == kiosk_id,
            KioskDevice.store_id == store.id,
            KioskDevice.active,
        )
    )
    if kiosk is None:
        raise NotFoundError("kiosk_device", str(kiosk_id))
    price_book = await get_current_price_book(session, store.id, at=now)
    tax_policy, tax_rates = await _current_tax_policy(
        session, legal_entity.tenant_id, store.country_code
    )
    lines = [
        await _calculate_line(
            session,
            line_number=index,
            store=store,
            tenant_id=legal_entity.tenant_id,
            price_book_id=price_book.id,
            prices_include_tax=price_book.prices_include_tax,
            locale=request.locale,
            product_id=item.product_id,
            quantity=item.quantity,
            selected_value_ids=item.option_value_ids,
            tax_rates=tax_rates,
        )
        for index, item in enumerate(request.items, start=1)
    ]
    packaging_fee = (
        policy.takeaway_fee_minor
        if request.fulfillment_type == FulfillmentType.TAKEAWAY
        and policy.takeaway_fee_enabled
        and policy.takeaway_fee_minor > 0
        else 0
    )
    item_subtotal = sum(line.base_minor for line in lines)
    subtotal = item_subtotal + packaging_fee
    promotion: Promotion | None = None
    total_discount = 0
    if request.promotion_code:
        promotion = await session.scalar(
            select(Promotion).where(
                Promotion.store_id == store.id,
                Promotion.code == normalize_code(request.promotion_code),
                Promotion.active,
                Promotion.starts_at <= now,
                or_(Promotion.ends_at.is_(None), Promotion.ends_at > now),
            )
        )
        if promotion is None:
            raise ConflictError("promotion_invalid", "The promotion code is invalid or inactive")
        if item_subtotal < promotion.minimum_total_minor:
            raise ConflictError("promotion_minimum_not_met", "The promotion minimum was not met")
        if promotion.promotion_type == PromotionType.PERCENTAGE:
            total_discount = _round_half_up(item_subtotal * promotion.value, 1_000_000)
        else:
            total_discount = min(promotion.value, item_subtotal)
    discounts = _allocate_discount(total_discount, [line.base_minor for line in lines])
    for line, discount in zip(lines, discounts, strict=True):
        line.discount_minor = discount
        discounted_base = line.base_minor - discount
        if price_book.prices_include_tax:
            line.total_minor = discounted_base
            line.tax_minor = _round_half_up(
                discounted_base * line.tax_rate_ppm,
                1_000_000 + line.tax_rate_ppm,
            )
            line.net_minor = line.total_minor - line.tax_minor
        else:
            line.net_minor = discounted_base
            line.tax_minor = _round_half_up(discounted_base * line.tax_rate_ppm, 1_000_000)
            line.total_minor = line.net_minor + line.tax_minor

    fee_tax_category = lines[0].product.tax_category_code
    fee_tax_rate = lines[0].tax_rate_ppm
    if price_book.prices_include_tax:
        fee_tax = _round_half_up(packaging_fee * fee_tax_rate, 1_000_000 + fee_tax_rate)
        fee_net = packaging_fee - fee_tax
        fee_total = packaging_fee
    else:
        fee_net = packaging_fee
        fee_tax = _round_half_up(packaging_fee * fee_tax_rate, 1_000_000)
        fee_total = fee_net + fee_tax
    net_total = sum(line.net_minor for line in lines) + fee_net
    tax_total = sum(line.tax_minor for line in lines) + fee_tax
    total = sum(line.total_minor for line in lines) + fee_total
    quote = PriceQuote(
        store_id=store.id,
        kiosk_id=kiosk.id,
        price_book_id=price_book.id,
        tax_policy_version_id=tax_policy.id,
        promotion_id=promotion.id if promotion else None,
        status=QuoteStatus.ACTIVE,
        request_hash=_request_hash(request),
        currency=price_book.currency,
        locale=request.locale,
        prices_include_tax=price_book.prices_include_tax,
        fulfillment_type=request.fulfillment_type,
        packaging_fee_minor=packaging_fee,
        subtotal_minor=subtotal,
        discount_minor=total_discount,
        net_minor=net_total,
        tax_minor=tax_total,
        total_minor=total,
        snapshot={
            "schema_version": 1,
            "price_book_id": str(price_book.id),
            "tax_policy_version_id": str(tax_policy.id),
            "promotion_code": promotion.code if promotion else None,
            "fulfillment_type": request.fulfillment_type.value,
            "packaging_fee_minor": packaging_fee,
        },
        expires_at=now + timedelta(seconds=settings.quote_ttl_seconds),
    )
    session.add(quote)
    await session.flush()
    item_responses: list[QuoteItemResponse] = []
    tax_totals: dict[tuple[str, int], list[int]] = defaultdict(lambda: [0, 0])
    for line in lines:
        quote_item = PriceQuoteItem(
            quote_id=quote.id,
            line_number=line.line_number,
            product_id=line.product.id,
            sku_snapshot=line.product.sku,
            name_snapshot=line.name,
            quantity=line.quantity,
            prices_include_tax=price_book.prices_include_tax,
            unit_price_minor=line.unit_price_minor,
            option_total_minor=sum(option.price_delta_minor for option in line.options),
            discount_minor=line.discount_minor,
            tax_category_code=line.product.tax_category_code,
            tax_rate_ppm=line.tax_rate_ppm,
            net_minor=line.net_minor,
            tax_minor=line.tax_minor,
            line_total_minor=line.total_minor,
            preparation_snapshot=deepcopy(line.product.preparation_data),
            allergen_snapshot=deepcopy(line.product.allergen_data),
        )
        session.add(quote_item)
        await session.flush()
        session.add_all(
            PriceQuoteItemOption(
                quote_item_id=quote_item.id,
                option_number=index,
                option_group_id=option.group_id,
                option_value_id=option.value_id,
                group_code_snapshot=option.group_code,
                group_name_snapshot=option.group_name,
                value_code_snapshot=option.value_code,
                name_snapshot=option.value_name,
                price_delta_minor=option.price_delta_minor,
            )
            for index, option in enumerate(line.options, start=1)
        )
        tax_bucket = tax_totals[(line.product.tax_category_code, line.tax_rate_ppm)]
        tax_bucket[0] += line.net_minor
        tax_bucket[1] += line.tax_minor
        item_responses.append(
            QuoteItemResponse(
                line_number=line.line_number,
                product_id=line.product.id,
                sku=line.product.sku,
                name=line.name,
                quantity=line.quantity,
                unit_price_minor=line.unit_price_minor,
                option_total_minor=sum(option.price_delta_minor for option in line.options),
                discount_minor=line.discount_minor,
                net_minor=line.net_minor,
                tax_minor=line.tax_minor,
                line_total_minor=line.total_minor,
                options=[
                    QuoteOptionResponse(
                        option_value_id=option.value_id,
                        group_name=option.group_name,
                        name=option.value_name,
                        price_delta_minor=option.price_delta_minor,
                    )
                    for option in line.options
                ],
                allergen_snapshot=deepcopy(line.product.allergen_data),
            )
        )
    if packaging_fee:
        fee_bucket = tax_totals[(fee_tax_category, fee_tax_rate)]
        fee_bucket[0] += fee_net
        fee_bucket[1] += fee_tax
    tax_responses: list[QuoteTaxLineResponse] = []
    for (tax_category_code, rate_ppm), (taxable_minor, tax_minor) in sorted(tax_totals.items()):
        session.add(
            PriceQuoteTaxLine(
                quote_id=quote.id,
                tax_category_code=tax_category_code,
                tax_rate_ppm=rate_ppm,
                taxable_minor=taxable_minor,
                tax_minor=tax_minor,
            )
        )
        tax_responses.append(
            QuoteTaxLineResponse(
                tax_category_code=tax_category_code,
                tax_rate_ppm=rate_ppm,
                taxable_minor=taxable_minor,
                tax_minor=tax_minor,
            )
        )
    if promotion is not None and total_discount:
        session.add(
            PriceQuoteDiscountLine(
                quote_id=quote.id,
                promotion_id=promotion.id,
                code_snapshot=promotion.code,
                amount_minor=total_discount,
            )
        )
    await session.flush()
    return QuoteResponse(
        id=quote.id,
        status=quote.status,
        store_id=quote.store_id,
        kiosk_id=quote.kiosk_id,
        currency=quote.currency,
        locale=quote.locale,
        prices_include_tax=quote.prices_include_tax,
        fulfillment_type=quote.fulfillment_type,
        packaging_fee_minor=quote.packaging_fee_minor,
        subtotal_minor=quote.subtotal_minor,
        discount_minor=quote.discount_minor,
        net_minor=quote.net_minor,
        tax_minor=quote.tax_minor,
        total_minor=quote.total_minor,
        expires_at=quote.expires_at,
        items=item_responses,
        tax_lines=tax_responses,
    )
