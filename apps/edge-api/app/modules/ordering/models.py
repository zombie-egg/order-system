from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ActorType, OrderStatus, PaymentStatus
from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class StoreNumberSequence(Base):
    __tablename__ = "store_number_sequence"
    __table_args__ = (CheckConstraint("next_value > 0", name="next_value_positive"),)

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, primary_key=True)
    sequence_kind: Mapped[str] = mapped_column(String(30), primary_key=True)
    next_value: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class SalesOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sales_order"
    __table_args__ = (
        UniqueConstraint("store_id", "business_date", "sequence_number"),
        UniqueConstraint("store_id", "order_number"),
        CheckConstraint("sequence_number > 0", name="sequence_number_positive"),
        CheckConstraint("subtotal_minor >= 0", name="subtotal_minor_nonnegative"),
        CheckConstraint("discount_minor >= 0", name="discount_minor_nonnegative"),
        CheckConstraint("net_minor >= 0", name="net_minor_nonnegative"),
        CheckConstraint("tax_minor >= 0", name="tax_minor_nonnegative"),
        CheckConstraint("total_minor >= 0", name="total_minor_nonnegative"),
        CheckConstraint("paid_minor >= 0", name="paid_minor_nonnegative"),
        CheckConstraint("refunded_minor >= 0", name="refunded_minor_nonnegative"),
        CheckConstraint(
            "(prices_include_tax AND subtotal_minor - discount_minor = total_minor) "
            "OR ((NOT prices_include_tax) AND "
            "subtotal_minor - discount_minor + tax_minor = total_minor)",
            name="total_arithmetic",
        ),
        CheckConstraint("net_minor + tax_minor = total_minor", name="net_tax_arithmetic"),
        CheckConstraint("refunded_minor <= paid_minor", name="refund_not_above_paid"),
        CheckConstraint("paid_minor <= total_minor", name="paid_not_above_total"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    kiosk_id: Mapped[UUID] = mapped_column(ForeignKey("kiosk_device.id"), nullable=False)
    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_quote.id"), unique=True, nullable=False
    )
    business_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    order_number: Mapped[str] = mapped_column(String(80), nullable=False)
    display_number: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        string_enum(OrderStatus, name="order_status"), default=OrderStatus.DRAFT, nullable=False
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        string_enum(PaymentStatus, name="order_payment_status"),
        default=PaymentStatus.UNPAID,
        index=True,
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    paid_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    refunded_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    cancellation_reason: Mapped[str | None] = mapped_column(String(300))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class OrderItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "order_item"
    __table_args__ = (
        UniqueConstraint("order_id", "line_number"),
        CheckConstraint("line_number > 0", name="line_number_positive"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price_minor >= 0", name="unit_price_minor_nonnegative"),
        CheckConstraint(
            "unit_price_minor + option_total_minor >= 0", name="configured_unit_nonnegative"
        ),
        CheckConstraint("discount_minor >= 0", name="discount_minor_nonnegative"),
        CheckConstraint("net_minor >= 0", name="net_minor_nonnegative"),
        CheckConstraint("tax_minor >= 0", name="tax_minor_nonnegative"),
        CheckConstraint("line_total_minor >= 0", name="line_total_minor_nonnegative"),
        CheckConstraint("tax_rate_ppm >= 0 AND tax_rate_ppm <= 1000000", name="tax_rate_ppm_valid"),
        CheckConstraint("net_minor + tax_minor = line_total_minor", name="net_tax_arithmetic"),
        CheckConstraint(
            "(prices_include_tax AND "
            "((unit_price_minor + option_total_minor) * quantity) "
            "- discount_minor = line_total_minor) "
            "OR ((NOT prices_include_tax) AND "
            "((unit_price_minor + option_total_minor) * quantity) "
            "- discount_minor + tax_minor = line_total_minor)",
            name="line_total_arithmetic",
        ),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"), nullable=False)
    sku_snapshot: Mapped[str] = mapped_column(String(100), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, nullable=False)
    unit_price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    option_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_category_code: Mapped[str] = mapped_column(String(80), nullable=False)
    tax_rate_ppm: Mapped[int] = mapped_column(Integer, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    line_total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    preparation_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    allergen_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class OrderItemOption(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "order_item_option"
    __table_args__ = (
        UniqueConstraint("order_item_id", "option_number"),
        CheckConstraint("option_number > 0", name="option_number_positive"),
    )

    order_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("order_item.id"), index=True, nullable=False
    )
    option_number: Mapped[int] = mapped_column(Integer, nullable=False)
    option_group_id: Mapped[UUID] = mapped_column(ForeignKey("option_group.id"), nullable=False)
    option_value_id: Mapped[UUID] = mapped_column(ForeignKey("option_value.id"), nullable=False)
    group_code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    group_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    value_code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    price_delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class OrderTaxLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "order_tax_line"
    __table_args__ = (
        UniqueConstraint("order_id", "tax_category_code", "tax_rate_ppm"),
        CheckConstraint("tax_rate_ppm >= 0 AND tax_rate_ppm <= 1000000", name="rate_valid"),
        CheckConstraint("taxable_minor >= 0", name="taxable_minor_nonnegative"),
        CheckConstraint("tax_minor >= 0", name="tax_minor_nonnegative"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    tax_category_code: Mapped[str] = mapped_column(String(80), nullable=False)
    tax_rate_ppm: Mapped[int] = mapped_column(Integer, nullable=False)
    taxable_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class OrderDiscountLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "order_discount_line"
    __table_args__ = (CheckConstraint("amount_minor > 0", name="amount_minor_positive"),)

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    order_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("order_item.id"))
    promotion_id: Mapped[UUID | None] = mapped_column(ForeignKey("promotion.id"))
    code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class OrderStatusEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "order_status_event"
    __table_args__ = (
        UniqueConstraint("order_id", "sequence_number"),
        CheckConstraint("sequence_number > 0", name="sequence_number_positive"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[OrderStatus | None] = mapped_column(
        string_enum(OrderStatus, name="order_event_from_status")
    )
    to_status: Mapped[OrderStatus] = mapped_column(
        string_enum(OrderStatus, name="order_event_to_status"), nullable=False
    )
    actor_type: Mapped[ActorType] = mapped_column(
        string_enum(ActorType, name="order_event_actor_type"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id"))
    actor_device_id: Mapped[UUID | None] = mapped_column(ForeignKey("kiosk_device.id"))
    reason_code: Mapped[str | None] = mapped_column(String(100))
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
