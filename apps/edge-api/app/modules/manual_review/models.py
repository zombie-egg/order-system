from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import FulfillmentFailureReason, ReviewResolution, ReviewStatus
from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class ManualReviewCase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "manual_review_case"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="priority_nonnegative"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    fulfillment_ticket_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("fulfillment_ticket.id"), unique=True, nullable=True
    )
    case_number: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    status: Mapped[ReviewStatus] = mapped_column(
        string_enum(ReviewStatus, name="review_status"),
        default=ReviewStatus.OPEN,
        index=True,
        nullable=False,
    )
    reason_code: Mapped[FulfillmentFailureReason] = mapped_column(
        string_enum(FulfillmentFailureReason, name="review_failure_reason"), nullable=False
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    assigned_to: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id"))
    resolution_code: Mapped[ReviewResolution | None] = mapped_column(
        string_enum(ReviewResolution, name="review_resolution")
    )
    sla_due_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    assigned_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    resolved_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class ManualReviewAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "manual_review_action"
    __table_args__ = (
        UniqueConstraint("case_id", "sequence_number"),
        CheckConstraint("sequence_number > 0", name="sequence_number_positive"),
    )

    case_id: Mapped[UUID] = mapped_column(ForeignKey("manual_review_case.id"), index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    action_type: Mapped[ReviewResolution] = mapped_column(
        string_enum(ReviewResolution, name="review_action_type"), nullable=False
    )
    actor_user_id: Mapped[UUID] = mapped_column(ForeignKey("user_account.id"), nullable=False)
    notes: Mapped[str] = mapped_column(String(2000), default="", nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    related_refund_id: Mapped[UUID | None] = mapped_column(ForeignKey("refund.id"))
    related_ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("fulfillment_ticket.id"))
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
