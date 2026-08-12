from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.core.api_models import StrictRequestModel
from app.core.sensitive_data import contains_sensitive_card_data

LOCALE_PATTERN = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
MAX_TRANSLATIONS = 20
MAX_DOMAIN_JSON_BYTES = 32_768


def _validate_locale(locale: str) -> str:
    normalized = locale.strip()
    if len(normalized) > 20 or LOCALE_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"Invalid locale: {locale}")
    return normalized


def _validate_simple_translations(values: dict[str, str]) -> dict[str, str]:
    if len(values) > MAX_TRANSLATIONS:
        raise ValueError(f"At most {MAX_TRANSLATIONS} translations are allowed")
    normalized: dict[str, str] = {}
    seen_locales: set[str] = set()
    for locale, value in values.items():
        normalized_locale = _validate_locale(locale)
        locale_key = normalized_locale.casefold()
        if locale_key in seen_locales:
            raise ValueError("Translation locales must be distinct")
        stripped_value = value.strip()
        if not stripped_value or len(stripped_value) > 200:
            raise ValueError("Translation names must contain 1 to 200 characters")
        seen_locales.add(locale_key)
        normalized[normalized_locale] = stripped_value
    return normalized


def _validate_domain_json(value: dict[str, Any], field_name: str) -> dict[str, Any]:
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be JSON serializable") from exc
    if len(encoded) > MAX_DOMAIN_JSON_BYTES:
        raise ValueError(f"{field_name} must not exceed {MAX_DOMAIN_JSON_BYTES} UTF-8 bytes")
    if contains_sensitive_card_data(value):
        raise ValueError(f"{field_name} must not contain payment-card authentication data")
    return value


def _validate_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")


class CreateCategoryRequest(StrictRequestModel):
    store_id: UUID
    code: str = Field(min_length=1, max_length=80)
    translations: dict[str, str] = Field(min_length=1)
    sort_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_translations(self) -> CreateCategoryRequest:
        self.translations = _validate_simple_translations(self.translations)
        return self


class CreateOptionValueInput(StrictRequestModel):
    code: str = Field(min_length=1, max_length=80)
    translations: dict[str, str] = Field(min_length=1)
    sort_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_translations(self) -> CreateOptionValueInput:
        self.translations = _validate_simple_translations(self.translations)
        return self


class CreateOptionGroupRequest(StrictRequestModel):
    store_id: UUID
    code: str = Field(min_length=1, max_length=80)
    translations: dict[str, str] = Field(min_length=1)
    sort_order: int = Field(default=0, ge=0)
    values: list[CreateOptionValueInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_group(self) -> CreateOptionGroupRequest:
        self.translations = _validate_simple_translations(self.translations)
        normalized_codes = [value.code.strip().casefold() for value in self.values]
        if len(set(normalized_codes)) != len(normalized_codes):
            raise ValueError("Option value codes must be distinct")
        return self


class ProductTranslationInput(StrictRequestModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_content(self) -> ProductTranslationInput:
        self.name = self.name.strip()
        self.description = self.description.strip()
        if not self.name:
            raise ValueError("Product translation name cannot be blank")
        return self


class ProductOptionRuleInput(StrictRequestModel):
    option_group_id: UUID
    minimum_selections: int = Field(default=0, ge=0, le=20)
    maximum_selections: int = Field(default=1, ge=1, le=20)
    sort_order: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> ProductOptionRuleInput:
        if self.maximum_selections < self.minimum_selections:
            raise ValueError("maximum_selections must be at least minimum_selections")
        return self


class CreateProductRequest(StrictRequestModel):
    store_id: UUID
    category_id: UUID
    sku: str = Field(min_length=1, max_length=100)
    tax_category_code: str = Field(min_length=1, max_length=80)
    image_url: HttpUrl | None = None
    translations: dict[str, ProductTranslationInput] = Field(min_length=1)
    preparation_data: dict[str, Any] = Field(default_factory=dict)
    allergen_data: dict[str, Any] = Field(default_factory=dict)
    sort_order: int = Field(default=0, ge=0)
    option_rules: list[ProductOptionRuleInput] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_product(self) -> CreateProductRequest:
        if len(self.translations) > MAX_TRANSLATIONS:
            raise ValueError(f"At most {MAX_TRANSLATIONS} translations are allowed")
        normalized_translations: dict[str, ProductTranslationInput] = {}
        seen_locales: set[str] = set()
        for locale, translation in self.translations.items():
            normalized_locale = _validate_locale(locale)
            locale_key = normalized_locale.casefold()
            if locale_key in seen_locales:
                raise ValueError("Translation locales must be distinct")
            seen_locales.add(locale_key)
            normalized_translations[normalized_locale] = translation
        self.translations = normalized_translations
        self.preparation_data = _validate_domain_json(self.preparation_data, "preparation_data")
        self.allergen_data = _validate_domain_json(self.allergen_data, "allergen_data")
        group_ids = [rule.option_group_id for rule in self.option_rules]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("A product can reference each option group only once")
        return self


class SetProductAvailabilityRequest(StrictRequestModel):
    available: bool
    expected_version: int = Field(ge=1)


class PriceBookOptionPriceInput(StrictRequestModel):
    option_value_id: UUID
    price_delta_minor: int = Field(ge=-1_000_000, le=1_000_000)


class PriceBookProductInput(StrictRequestModel):
    product_id: UUID
    price_minor: int = Field(ge=0, le=100_000_000)
    option_prices: list[PriceBookOptionPriceInput] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def validate_option_prices(self) -> PriceBookProductInput:
        value_ids = [option.option_value_id for option in self.option_prices]
        if len(set(value_ids)) != len(value_ids):
            raise ValueError("Option prices must reference distinct option values")
        return self


class CreatePriceBookRequest(StrictRequestModel):
    store_id: UUID
    code: str = Field(min_length=1, max_length=80)
    version: int = Field(ge=1)
    currency: str = Field(min_length=3, max_length=3)
    prices_include_tax: bool = True
    valid_from: datetime
    valid_to: datetime | None = None
    items: list[PriceBookProductInput] = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_price_book(self) -> CreatePriceBookRequest:
        _validate_aware_datetime(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _validate_aware_datetime(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be after valid_from")
        product_ids = [item.product_id for item in self.items]
        if len(set(product_ids)) != len(product_ids):
            raise ValueError("A price book can price each product only once")
        return self


class ResourceCreatedResponse(BaseModel):
    id: UUID


class CatalogOptionValueResponse(BaseModel):
    id: UUID
    code: str
    name: str
    price_delta_minor: int


class CatalogOptionGroupResponse(BaseModel):
    id: UUID
    code: str
    name: str
    minimum_selections: int
    maximum_selections: int
    values: list[CatalogOptionValueResponse]


class CatalogProductResponse(BaseModel):
    id: UUID
    sku: str
    name: str
    description: str
    image_url: str | None
    price_minor: int
    currency: str
    tax_category_code: str
    allergen_data: dict[str, Any]
    option_groups: list[CatalogOptionGroupResponse]


class CatalogCategoryResponse(BaseModel):
    id: UUID
    code: str
    name: str
    products: list[CatalogProductResponse]


class StoreCatalogResponse(BaseModel):
    store_id: UUID
    locale: str
    currency: str
    price_book_id: UUID
    categories: list[CatalogCategoryResponse]
