from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, CheckConstraint, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ActorType, FulfillmentFailureReason, FulfillmentStatus
from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class FulfillmentTicket(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fulfillment_ticket"
    __table_args__ = (
        UniqueConstraint("order_id", "station_id", "generation_number"),
        CheckConstraint("generation_number > 0", name="generation_number_positive"),
        CheckConstraint("priority >= 0", name="priority_nonnegative"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    order_id: Mapped[UUID] = mapped_column(ForeignKey("sales_order.id"), index=True, nullable=False)
    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("kitchen_station.id"), index=True, nullable=False
    )
    source_ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("fulfillment_ticket.id"))
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    display_number: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[FulfillmentStatus] = mapped_column(
        string_enum(FulfillmentStatus, name="fulfillment_status"),
        default=FulfillmentStatus.QUEUED,
        index=True,
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preparation_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    failure_reason_code: Mapped[FulfillmentFailureReason | None] = mapped_column(
        string_enum(FulfillmentFailureReason, name="fulfillment_failure_reason")
    )
    failure_detail: Mapped[str | None] = mapped_column(String(1000))
    acknowledged_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id"))
    acknowledged_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    started_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id"))
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    ready_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id"))
    ready_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    collected_by: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id"))
    collected_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class FulfillmentTicketItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fulfillment_ticket_item"
    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)

    ticket_id: Mapped[UUID] = mapped_column(
        ForeignKey("fulfillment_ticket.id"), index=True, nullable=False
    )
    order_item_id: Mapped[UUID] = mapped_column(ForeignKey("order_item.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    name_snapshot: Mapped[str] = mapped_column(String(200), nullable=False)
    preparation_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    allergen_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class FulfillmentEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "fulfillment_event"
    __table_args__ = (
        UniqueConstraint("ticket_id", "sequence_number"),
        CheckConstraint("sequence_number > 0", name="sequence_number_positive"),
    )

    ticket_id: Mapped[UUID] = mapped_column(
        ForeignKey("fulfillment_ticket.id"), index=True, nullable=False
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[FulfillmentStatus | None] = mapped_column(
        string_enum(FulfillmentStatus, name="fulfillment_event_from_status")
    )
    to_status: Mapped[FulfillmentStatus] = mapped_column(
        string_enum(FulfillmentStatus, name="fulfillment_event_to_status"), nullable=False
    )
    actor_type: Mapped[ActorType] = mapped_column(
        string_enum(ActorType, name="fulfillment_event_actor_type"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(ForeignKey("user_account.id"))
    actor_device_id: Mapped[UUID | None] = mapped_column(ForeignKey("fulfillment_endpoint.id"))
    reason_code: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
