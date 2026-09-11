from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.api_models import StrictRequestModel
from app.core.enums import FulfillmentType, PromotionType, QuoteStatus


def _validate_aware_datetime(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a UTC offset")


class TaxRateInput(StrictRequestModel):
    tax_category_code: str = Field(min_length=1, max_length=80)
    rate_ppm: int = Field(ge=0, le=1_000_000)


class CreateTaxPolicyRequest(StrictRequestModel):
    store_id: UUID
    version: int = Field(ge=1)
    rounding_mode: str = Field(default="HALF_UP", pattern="^HALF_UP$")
    rounding_scope: str = Field(default="LINE", pattern="^LINE$")
    valid_from: datetime
    valid_to: datetime | None = None
    rates: list[TaxRateInput] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_policy(self) -> CreateTaxPolicyRequest:
        _validate_aware_datetime(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _validate_aware_datetime(self.valid_to, "valid_to")
            if self.valid_to <= self.valid_from:
                raise ValueError("valid_to must be after valid_from")
        categories = [rate.tax_category_code.strip().casefold() for rate in self.rates]
        if len(set(categories)) != len(categories):
            raise ValueError("Tax category codes must be distinct")
        return self


class CreatePromotionRequest(StrictRequestModel):
    store_id: UUID
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    promotion_type: PromotionType
    value: int = Field(gt=0, le=1_000_000_000)
    minimum_total_minor: int = Field(default=0, ge=0)
    starts_at: datetime
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def validate_promotion(self) -> CreatePromotionRequest:
        _validate_aware_datetime(self.starts_at, "starts_at")
        if self.ends_at is not None:
            _validate_aware_datetime(self.ends_at, "ends_at")
            if self.ends_at <= self.starts_at:
                raise ValueError("ends_at must be after starts_at")
        if self.promotion_type == PromotionType.PERCENTAGE and self.value > 1_000_000:
            raise ValueError("Percentage promotion value cannot exceed 100%")
        return self


class QuoteItemRequest(StrictRequestModel):
    product_id: UUID
    quantity: int = Field(ge=1, le=20)
    option_value_ids: list[UUID] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def validate_options(self) -> QuoteItemRequest:
        if len(set(self.option_value_ids)) != len(self.option_value_ids):
            raise ValueError("Option values must be distinct within a quote line")
        return self


class CreateQuoteRequest(StrictRequestModel):
    locale: str = Field(min_length=2, max_length=20)
    fulfillment_type: FulfillmentType
    items: list[QuoteItemRequest] = Field(min_length=1, max_length=50)
    promotion_code: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def validate_order_size(self) -> CreateQuoteRequest:
        if sum(item.quantity for item in self.items) > 100:
            raise ValueError("A quote cannot contain more than 100 total items")
        return self


class QuoteOptionResponse(BaseModel):
    option_value_id: UUID
    group_name: str
    name: str
    price_delta_minor: int


class QuoteItemResponse(BaseModel):
    line_number: int
    product_id: UUID
    sku: str
    name: str
    quantity: int
    unit_price_minor: int
    option_total_minor: int
    discount_minor: int
    net_minor: int
    tax_minor: int
    line_total_minor: int
    options: list[QuoteOptionResponse]
    allergen_snapshot: dict[str, Any]


class QuoteTaxLineResponse(BaseModel):
    tax_category_code: str
    tax_rate_ppm: int
    taxable_minor: int
    tax_minor: int


class QuoteResponse(BaseModel):
    id: UUID
    status: QuoteStatus
    store_id: UUID
    kiosk_id: UUID
    currency: str
    locale: str
    prices_include_tax: bool
    fulfillment_type: FulfillmentType
    packaging_fee_minor: int
    subtotal_minor: int
    discount_minor: int
    net_minor: int
    tax_minor: int
    total_minor: int
    expires_at: datetime
    items: list[QuoteItemResponse]
    tax_lines: list[QuoteTaxLineResponse]
