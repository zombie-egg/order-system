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

from app.core.enums import PriceBookStatus
from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "category"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class CategoryTranslation(Base):
    __tablename__ = "category_translation"

    category_id: Mapped[UUID] = mapped_column(
        ForeignKey("category.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)


class Product(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    category_id: Mapped[UUID] = mapped_column(ForeignKey("category.id"), index=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    tax_category_code: Mapped[str] = mapped_column(String(80), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1000))
    preparation_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    allergen_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ProductTranslation(Base):
    __tablename__ = "product_translation"

    product_id: Mapped[UUID] = mapped_column(
        ForeignKey("product.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), default="", nullable=False)


class OptionGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "option_group"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class OptionGroupTranslation(Base):
    __tablename__ = "option_group_translation"

    option_group_id: Mapped[UUID] = mapped_column(
        ForeignKey("option_group.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)


class OptionValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "option_value"
    __table_args__ = (UniqueConstraint("option_group_id", "code"),)

    option_group_id: Mapped[UUID] = mapped_column(
        ForeignKey("option_group.id"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class OptionValueTranslation(Base):
    __tablename__ = "option_value_translation"

    option_value_id: Mapped[UUID] = mapped_column(
        ForeignKey("option_value.id", ondelete="CASCADE"), primary_key=True
    )
    locale: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)


class ProductOptionRule(Base):
    __tablename__ = "product_option_rule"
    __table_args__ = (
        CheckConstraint(
            "minimum_selections >= 0 AND maximum_selections >= minimum_selections",
            name="selection_bounds",
        ),
    )

    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"), primary_key=True)
    option_group_id: Mapped[UUID] = mapped_column(ForeignKey("option_group.id"), primary_key=True)
    minimum_selections: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    maximum_selections: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StoreProductAvailability(Base):
    __tablename__ = "store_product_availability"
    __table_args__ = (CheckConstraint("version > 0", name="version_positive"),)

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"), primary_key=True)
    available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PriceBook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "price_book"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    prices_include_tax: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    status: Mapped[PriceBookStatus] = mapped_column(
        string_enum(PriceBookStatus, name="price_book_status"), nullable=False
    )


class StorePriceBookAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "store_price_book_assignment"
    __table_args__ = (
        CheckConstraint("valid_to IS NULL OR valid_to > valid_from", name="validity_window"),
    )

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    price_book_id: Mapped[UUID] = mapped_column(ForeignKey("price_book.id"), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(UtcDateTime())


class PriceBookItem(Base):
    __tablename__ = "price_book_item"
    __table_args__ = (CheckConstraint("price_minor >= 0", name="price_minor_nonnegative"),)

    price_book_id: Mapped[UUID] = mapped_column(ForeignKey("price_book.id"), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"), primary_key=True)
    price_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)


class PriceBookOptionItem(Base):
    __tablename__ = "price_book_option_item"

    price_book_id: Mapped[UUID] = mapped_column(ForeignKey("price_book.id"), primary_key=True)
    product_id: Mapped[UUID] = mapped_column(ForeignKey("product.id"), primary_key=True)
    option_value_id: Mapped[UUID] = mapped_column(ForeignKey("option_value.id"), primary_key=True)
    price_delta_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
