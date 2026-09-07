from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.core.api_models import StrictRequestModel
from app.core.enums import (
    FulfillmentType,
    OrderStatus,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
)


class CreateOrderRequest(StrictRequestModel):
    quote_id: UUID
    payment_method: PaymentMethod = PaymentMethod.CARD


class RetryPaymentRequest(StrictRequestModel):
    payment_method: PaymentMethod = PaymentMethod.CARD


class OrderOptionResponse(BaseModel):
    option_value_id: UUID
    group_name: str
    name: str
    price_delta_minor: int


class OrderItemResponse(BaseModel):
    id: UUID
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
    allergen_snapshot: dict[str, Any]
    options: list[OrderOptionResponse]


class PaymentAttemptResponse(BaseModel):
    id: UUID
    attempt_number: int
    provider: PaymentProvider
    payment_method: PaymentMethod
    status: PaymentStatus
    amount_minor: int
    currency: str
    psp_reference: str | None
    failure_code: str | None
    requested_at: datetime
    completed_at: datetime | None
    version: int


class OrderResponse(BaseModel):
    id: UUID
    store_id: UUID
    kiosk_id: UUID
    quote_id: UUID
    business_date: date
    order_number: str
    display_number: str
    status: OrderStatus
    payment_status: PaymentStatus
    currency: str
    locale: str
    prices_include_tax: bool
    fulfillment_type: FulfillmentType = FulfillmentType.DINE_IN
    packaging_fee_minor: int = 0
    subtotal_minor: int
    discount_minor: int
    net_minor: int
    tax_minor: int
    total_minor: int
    paid_minor: int
    refunded_minor: int
    confirmed_at: datetime | None
    closed_at: datetime | None
    version: int
    items: list[OrderItemResponse]
    payment_attempts: list[PaymentAttemptResponse]


class KioskOrderOptionResponse(BaseModel):
    group_name: str
    name: str
    price_delta_minor: int


class KioskOrderItemResponse(BaseModel):
    line_number: int
    name: str
    quantity: int
    unit_price_minor: int
    option_total_minor: int
    discount_minor: int
    net_minor: int
    tax_minor: int
    line_total_minor: int
    allergen_snapshot: dict[str, Any]
    options: list[KioskOrderOptionResponse]


class KioskPaymentAttemptResponse(BaseModel):
    id: UUID
    payment_method: PaymentMethod
    status: PaymentStatus
    amount_minor: int
    currency: str


class KioskOrderResponse(BaseModel):
    id: UUID
    display_number: str
    status: OrderStatus
    payment_status: PaymentStatus
    currency: str
    locale: str
    prices_include_tax: bool
    fulfillment_type: FulfillmentType = FulfillmentType.DINE_IN
    packaging_fee_minor: int = 0
    subtotal_minor: int
    discount_minor: int
    net_minor: int
    tax_minor: int
    total_minor: int
    paid_minor: int
    refunded_minor: int
    items: list[KioskOrderItemResponse]
    payment_attempts: list[KioskPaymentAttemptResponse]


def to_kiosk_order_response(order: OrderResponse) -> KioskOrderResponse:
    return KioskOrderResponse.model_validate(order.model_dump())


class OrderListQuery(StrictRequestModel):
    limit: int = Field(default=100, ge=1, le=500)
