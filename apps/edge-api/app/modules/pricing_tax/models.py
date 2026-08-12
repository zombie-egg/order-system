from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PromotionType, QuoteStatus
from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class TaxPolicyVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tax_policy_version"
    __table_args__ = (
        UniqueConstraint("tenant_id", "country_code", "version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(country_code) = 2", name="country_code_length"),
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="validity_window"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), index=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rounding_mode: Mapped[str] = mapped_column(String(30), default="HALF_UP", nullable=False)
    rounding_scope: Mapped[str] = mapped_column(String(30), default="LINE", nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(UtcDateTime())
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class TaxRate(Base):
    __tablename__ = "tax_rate"
    __table_args__ = (
        CheckConstraint("rate_ppm >= 0 AND rate_ppm <= 1000000", name="rate_ppm_valid"),
    )

    tax_policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("tax_policy_version.id"), primary_key=True
    )
    tax_category_code: Mapped[str] = mapped_column(String(80), primary_key=True)
    rate_ppm: Mapped[int] = mapped_column(Integer, nullable=False)


class Promotion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "promotion"
    __table_args__ = (
        UniqueConstraint("store_id", "code"),
        CheckConstraint("value > 0", name="value_positive"),
        CheckConstraint(
            "promotion_type <> 'PERCENTAGE' OR value <= 1000000",
            name="percentage_value_valid",
        ),
        CheckConstraint("minimum_total_minor >= 0", name="minimum_total_minor_nonnegative"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="validity_window"),
    )

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    promotion_type: Mapped[PromotionType] = mapped_column(
        string_enum(PromotionType, name="promotion_type"), nullable=False
    )
    value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    minimum_total_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    ends_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PriceQuote(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "price_quote"
    __table_args__ = (
        CheckConstraint("subtotal_minor >= 0", name="subtotal_minor_nonnegative"),
        CheckConstraint("discount_minor >= 0", name="discount_minor_nonnegative"),
        CheckConstraint("net_minor >= 0", name="net_minor_nonnegative"),
        CheckConstraint("tax_minor >= 0", name="tax_minor_nonnegative"),
        CheckConstraint("total_minor >= 0", name="total_minor_nonnegative"),
        CheckConstraint(
            "(prices_include_tax AND subtotal_minor - discount_minor = total_minor) "
            "OR ((NOT prices_include_tax) AND "
            "subtotal_minor - discount_minor + tax_minor = total_minor)",
            name="total_arithmetic",
        ),
        CheckConstraint("net_minor + tax_minor = total_minor", name="net_tax_arithmetic"),
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
        CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
    )

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    kiosk_id: Mapped[UUID] = mapped_column(
        ForeignKey("kiosk_device.id"), index=True, nullable=False
    )
    price_book_id: Mapped[UUID] = mapped_column(ForeignKey("price_book.id"), nullable=False)
    tax_policy_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("tax_policy_version.id"), nullable=False
    )
    promotion_id: Mapped[UUID | None] = mapped_column(ForeignKey("promotion.id"))
    status: Mapped[QuoteStatus] = mapped_column(
        string_enum(QuoteStatus, name="quote_status"),
        default=QuoteStatus.ACTIVE,
        index=True,
        nullable=False,
    )
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, nullable=False)
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    net_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    total_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class PriceQuoteItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "price_quote_item"
    __table_args__ = (
        UniqueConstraint("quote_id", "line_number"),
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

    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_quote.id", ondelete="CASCADE"), index=True, nullable=False
    )
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


class PriceQuoteItemOption(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "price_quote_item_option"
    __table_args__ = (
        UniqueConstraint("quote_item_id", "option_number"),
        CheckConstraint("option_number > 0", name="option_number_positive"),
    )

    quote_item_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_quote_item.id", ondelete="CASCADE"), index=True, nullable=False
    )
    option_number: Mapped[int] = mapped_column(Integer, nullable=False)
    option_group_id: Mapped[UUID] = mapped_column(ForeignKey("option_group.id"), nullable=False)
    option_value_id: Mapped[UUID] = mapped_column(ForeignKey("option_value.id"), nullable=False)
    group_code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    group_name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    value_code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    price_delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PriceQuoteTaxLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "price_quote_tax_line"
    __table_args__ = (
        UniqueConstraint("quote_id", "tax_category_code", "tax_rate_ppm"),
        CheckConstraint("tax_rate_ppm >= 0 AND tax_rate_ppm <= 1000000", name="rate_valid"),
        CheckConstraint("taxable_minor >= 0", name="taxable_minor_nonnegative"),
        CheckConstraint("tax_minor >= 0", name="tax_minor_nonnegative"),
    )

    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_quote.id", ondelete="CASCADE"), index=True, nullable=False
    )
    tax_category_code: Mapped[str] = mapped_column(String(80), nullable=False)
    tax_rate_ppm: Mapped[int] = mapped_column(Integer, nullable=False)
    taxable_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    tax_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PriceQuoteDiscountLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "price_quote_discount_line"
    __table_args__ = (CheckConstraint("amount_minor > 0", name="amount_minor_positive"),)

    quote_id: Mapped[UUID] = mapped_column(
        ForeignKey("price_quote.id", ondelete="CASCADE"), index=True, nullable=False
    )
    quote_item_id: Mapped[UUID | None] = mapped_column(ForeignKey("price_quote_item.id"))
    promotion_id: Mapped[UUID | None] = mapped_column(ForeignKey("promotion.id"))
    code_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
