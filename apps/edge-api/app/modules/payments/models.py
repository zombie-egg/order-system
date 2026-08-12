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

from app.core.enums import (
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    PaymentTransactionKind,
    RefundStatus,
)
from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class PaymentAttempt(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_attempt"
    __table_args__ = (
        UniqueConstraint("order_id", "attempt_number"),
        UniqueConstraint("provider", "provider_service_id"),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint("amount_minor > 0", name="amount_minor_positive"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[PaymentProvider] = mapped_column(
        string_enum(PaymentProvider, name="attempt_payment_provider"), nullable=False
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        string_enum(PaymentMethod, name="payment_method"), nullable=False
    )
    terminal_id: Mapped[UUID | None] = mapped_column(ForeignKey("payment_terminal.id"))
    status: Mapped[PaymentStatus] = mapped_column(
        string_enum(PaymentStatus, name="payment_attempt_status"),
        default=PaymentStatus.INITIATED,
        index=True,
        nullable=False,
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    merchant_reference: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    provider_service_id: Mapped[str] = mapped_column(String(160), nullable=False)
    psp_reference: Mapped[str | None] = mapped_column(String(160), index=True)
    card_brand: Mapped[str | None] = mapped_column(String(40))
    masked_account: Mapped[str | None] = mapped_column(String(40))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    failure_detail_redacted: Mapped[str | None] = mapped_column(String(500))
    requested_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    last_status_check_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PaymentTransaction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "payment_transaction"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id"),
        CheckConstraint("amount_minor >= 0", name="amount_minor_nonnegative"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
    )

    attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_attempt.id"), index=True, nullable=False
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        string_enum(PaymentProvider, name="transaction_payment_provider"), nullable=False
    )
    transaction_kind: Mapped[PaymentTransactionKind] = mapped_column(
        string_enum(PaymentTransactionKind, name="payment_transaction_kind"), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        string_enum(PaymentStatus, name="payment_transaction_status"), nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    psp_reference: Mapped[str | None] = mapped_column(String(160))
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class Refund(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "refund"
    __table_args__ = (
        UniqueConstraint("payment_attempt_id", "request_key_hash"),
        CheckConstraint("amount_minor > 0", name="amount_minor_positive"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    payment_attempt_id: Mapped[UUID] = mapped_column(
        ForeignKey("payment_attempt.id"), index=True, nullable=False
    )
    request_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[RefundStatus] = mapped_column(
        string_enum(RefundStatus, name="refund_status"),
        default=RefundStatus.PENDING,
        index=True,
        nullable=False,
    )
    requested_by: Mapped[UUID] = mapped_column(ForeignKey("user_account.id"), nullable=False)
    psp_reference: Mapped[str | None] = mapped_column(String(160))
    failure_code: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PspWebhookEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "psp_webhook_event"
    __table_args__ = (
        UniqueConstraint("provider", "provider_event_id"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
    )

    provider: Mapped[PaymentProvider] = mapped_column(
        string_enum(PaymentProvider, name="webhook_payment_provider"), nullable=False
    )
    provider_event_id: Mapped[str] = mapped_column(String(160), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    received_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    processing_status: Mapped[str] = mapped_column(String(30), default="PENDING", nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(String(1000))


class ReconciliationRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_run"
    __table_args__ = (
        CheckConstraint(
            "completed_at IS NULL OR completed_at >= started_at", name="completion_not_before_start"
        ),
    )

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    provider: Mapped[PaymentProvider | None] = mapped_column(
        string_enum(PaymentProvider, name="reconciliation_payment_provider")
    )
    status: Mapped[str] = mapped_column(String(30), default="RUNNING", nullable=False)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class ReconciliationIssue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_issue"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "issue_code",
            "resource_type",
            "resource_id",
            name="uq_reconciliation_issue_run_resource_code",
        ),
    )

    run_id: Mapped[UUID] = mapped_column(ForeignKey("reconciliation_run.id"), nullable=False)
    issue_code: Mapped[str] = mapped_column(String(100), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID] = mapped_column(nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
