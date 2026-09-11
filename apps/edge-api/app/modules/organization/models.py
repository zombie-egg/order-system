from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import FulfillmentEndpointType, PaymentProvider
from app.persistence.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.persistence.types import UtcDateTime, string_enum


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenant"

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    brand_name: Mapped[str | None] = mapped_column(String(200))
    logo_url: Mapped[str | None] = mapped_column(String(1000))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class LegalEntity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "legal_entity"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        CheckConstraint("length(country_code) = 2", name="country_code_length"),
    )

    tenant_id: Mapped[UUID] = mapped_column(ForeignKey("tenant.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    vat_number: Mapped[str | None] = mapped_column(String(40))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Store(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "store"
    __table_args__ = (
        UniqueConstraint("legal_entity_id", "code"),
        CheckConstraint("length(country_code) = 2", name="country_code_length"),
        CheckConstraint("length(currency) = 3", name="currency_length"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    legal_entity_id: Mapped[UUID] = mapped_column(
        ForeignKey("legal_entity.id"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120), index=True)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="NL")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    locale: Mapped[str] = mapped_column(String(20), nullable=False, default="nl-NL")
    timezone: Mapped[str] = mapped_column(String(60), nullable=False, default="Europe/Amsterdam")
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class StoreOperatingPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "store_operating_policy"
    __table_args__ = (
        CheckConstraint("max_open_tickets > 0", name="max_open_tickets_positive"),
        CheckConstraint("kds_heartbeat_seconds > 0", name="heartbeat_seconds_positive"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("takeaway_fee_minor >= 0", name="takeaway_fee_minor_nonnegative"),
    )

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), unique=True, nullable=False)
    accepting_orders: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    max_open_tickets: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    kds_heartbeat_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    printer_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    takeaway_fee_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    takeaway_fee_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class KioskDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kiosk_device"
    __table_args__ = (UniqueConstraint("store_id", "code"),)

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    credential_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    app_version: Mapped[str | None] = mapped_column(String(40))
    last_seen_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class KitchenStation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "kitchen_station"
    __table_args__ = (
        UniqueConstraint("store_id", "code"),
        CheckConstraint("version > 0", name="version_positive"),
    )

    store_id: Mapped[UUID] = mapped_column(ForeignKey("store.id"), index=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_title: Mapped[str | None] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class FulfillmentEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "fulfillment_endpoint"
    __table_args__ = (
        UniqueConstraint(
            "station_id",
            "endpoint_type",
            "external_reference",
            name="uq_fulfillment_endpoint_station_type_reference",
        ),
        CheckConstraint("version > 0", name="version_positive"),
    )

    station_id: Mapped[UUID] = mapped_column(
        ForeignKey("kitchen_station.id"), index=True, nullable=False
    )
    endpoint_type: Mapped[FulfillmentEndpointType] = mapped_column(
        string_enum(FulfillmentEndpointType, name="fulfillment_endpoint_type"), nullable=False
    )
    external_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    credential_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(UtcDateTime())
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class PaymentTerminal(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "payment_terminal"
    __table_args__ = (UniqueConstraint("provider", "terminal_reference"),)

    kiosk_id: Mapped[UUID] = mapped_column(
        ForeignKey("kiosk_device.id"), unique=True, nullable=False
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        string_enum(PaymentProvider, name="payment_provider"),
        default=PaymentProvider.MOCK,
        nullable=False,
    )
    terminal_reference: Mapped[str] = mapped_column(String(160), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
