from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ReceiptType
from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class Receipt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "receipt"
    __table_args__ = (
        UniqueConstraint("store_id", "receipt_number"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
        CheckConstraint("print_attempt_count >= 0", name="print_attempt_count_nonnegative"),
        CheckConstraint(
            "printed_at IS NULL OR printed_at >= generated_at", name="print_not_before_generation"
        ),
        CheckConstraint(
            "(receipt_type = 'SALE' AND refund_id IS NULL) OR "
            "(receipt_type = 'REFUND' AND refund_id IS NOT NULL)",
            name="type_refund_consistent",
        ),
    )

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    refund_id: Mapped[UUID | None] = mapped_column(ForeignKey("refund.id"), unique=True)
    receipt_type: Mapped[ReceiptType] = mapped_column(
        string_enum(ReceiptType, name="receipt_type"), nullable=False
    )
    receipt_number: Mapped[str] = mapped_column(String(100), nullable=False)
    business_date: Mapped[date] = mapped_column(Date, nullable=False)
    locale: Mapped[str] = mapped_column(String(20), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="GENERATED", nullable=False)
    document_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    printed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    print_attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_print_error: Mapped[str | None] = mapped_column(String(1000))
