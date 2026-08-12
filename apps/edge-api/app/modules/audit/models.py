from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ActorType, IdempotencyStatus
from app.persistence.base import Base, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class IdempotencyRecord(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "idempotency_record"
    __table_args__ = (
        UniqueConstraint("namespace", "actor_scope", "idempotency_key"),
        CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 100 AND 599",
            name="response_status_valid",
        ),
        CheckConstraint("expires_at IS NULL OR expires_at > created_at", name="expiry_valid"),
    )

    namespace: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_scope: Mapped[str] = mapped_column(String(160), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[IdempotencyStatus] = mapped_column(
        string_enum(IdempotencyStatus, name="idempotency_status"), nullable=False
    )
    resource_type: Mapped[str | None] = mapped_column(String(80))
    resource_id: Mapped[UUID | None] = mapped_column()
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime())


class OutboxEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "outbox_event"
    __table_args__ = (
        CheckConstraint("schema_version > 0", name="schema_version_positive"),
        CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        CheckConstraint(
            "(locked_by IS NULL AND locked_at IS NULL) OR "
            "(locked_by IS NOT NULL AND locked_at IS NOT NULL)",
            name="lock_fields_consistent",
        ),
    )

    store_id: Mapped[UUID | None] = mapped_column(ForeignKey("store.id"), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80), nullable=False)
    aggregate_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    available_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True, nullable=False)
    locked_by: Mapped[str | None] = mapped_column(String(160))
    locked_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), index=True)
    last_error: Mapped[str | None] = mapped_column(String(2000))


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_log"

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    store_id: Mapped[UUID | None] = mapped_column(ForeignKey("store.id"), index=True)
    actor_type: Mapped[ActorType] = mapped_column(
        string_enum(ActorType, name="audit_actor_type"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id"), index=True)
    actor_device_id: Mapped[UUID | None] = mapped_column(index=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    target_type: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    target_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(80), index=True)
    before_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_redacted: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    metadata_redacted: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), index=True, nullable=False)
