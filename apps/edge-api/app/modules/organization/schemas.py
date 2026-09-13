from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.api_models import StrictRequestModel


class StoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    city: str | None = None
    country_code: str
    currency: str
    locale: str
    timezone: str
    active: bool
    version: int


class CreateStoreRequest(StrictRequestModel):
    name: str = Field(min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    locale: str = Field(default="nl-NL", min_length=2, max_length=20)
    timezone: str = Field(default="Europe/Amsterdam", min_length=3, max_length=60)
    manager_display_name: str = Field(min_length=1, max_length=160)
    manager_username: str = Field(min_length=1, max_length=120)
    manager_password: str = Field(min_length=12, max_length=1024)

    @field_validator("name", "manager_display_name", "manager_username")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value


class StorePolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: UUID
    accepting_orders: bool
    max_open_tickets: int
    kds_heartbeat_seconds: int
    printer_fallback_enabled: bool
    takeaway_fee_enabled: bool
    takeaway_fee_minor: int
    version: int


class StoreWithPolicyResponse(BaseModel):
    store: StoreResponse
    policy: StorePolicyResponse


class StoreDeviceCredentialsResponse(BaseModel):
    """Device identifiers, plus secrets only when freshly created or reset.

    On a plain read the secret fields are ``null``; they are populated exactly once
    by the create-store and reset-credentials responses.
    """

    store_id: UUID
    kiosk_id: UUID | None = None
    kiosk_code: str | None = None
    kiosk_key: str | None = None
    station_id: UUID | None = None
    endpoint_id: UUID | None = None
    endpoint_code: str | None = None
    endpoint_key: str | None = None
    terminal_id: UUID | None = None
    terminal_provider: str | None = None


class CreatedStoreResponse(StoreWithPolicyResponse):
    tenant_code: str
    device_credentials: StoreDeviceCredentialsResponse
    manager_account: StoreManagerResponse


class StoreManagerResponse(BaseModel):
    """A store-manager account attached to a store (secrets are never echoed)."""

    user_id: UUID
    username: str
    display_name: str
    active: bool


class StoreConnectionResponse(BaseModel):
    """Everything needed to wire up a store: tenant, kiosk/KDS devices, managers.

    Secret fields (``kiosk_key`` / ``endpoint_key``) are returned only by the
    create-store and reset responses; a plain read leaves them ``null``.
    """

    store_id: UUID
    store_code: str
    store_name: str
    tenant_code: str
    kiosk_id: UUID | None = None
    kiosk_key: str | None = None
    endpoint_id: UUID | None = None
    endpoint_key: str | None = None
    managers: list[StoreManagerResponse] = []


class UpdateStorePolicyRequest(StrictRequestModel):
    accepting_orders: bool
    max_open_tickets: int = Field(ge=1, le=1000)
    kds_heartbeat_seconds: int = Field(ge=5, le=300)
    printer_fallback_enabled: bool = False
    takeaway_fee_enabled: bool = False
    takeaway_fee_minor: int = Field(default=0, ge=0, le=100_000_000)
    expected_version: int = Field(ge=1)


class HeartbeatResponse(BaseModel):
    resource_id: UUID
    server_time: datetime


class KioskStoreStatusResponse(BaseModel):
    store_id: UUID
    accepting_orders: bool
    currency: str
    locale: str
    takeaway_fee_enabled: bool
    takeaway_fee_minor: int


class BrandingResponse(BaseModel):
    merchant_name: str
    logo_url: str | None = None


class UpdateBrandingRequest(StrictRequestModel):
    merchant_name: str | None = Field(default=None, min_length=1, max_length=200)
    logo_url: str | None = Field(default=None, max_length=1000)


class UpdateStoreRequest(StrictRequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    expected_version: int = Field(ge=1)


class KdsBoardResponse(BaseModel):
    """Per-store kitchen-display (KDS) board configuration."""

    store_id: UUID
    station_id: UUID
    code: str
    name: str
    display_title: str | None = None
    enabled: bool
    version: int


class UpdateKdsBoardRequest(StrictRequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    display_title: str | None = Field(default=None, max_length=120)
    enabled: bool | None = None
    expected_version: int = Field(ge=1)
