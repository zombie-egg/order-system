from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.api_models import StrictRequestModel


class StoreResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str
    country_code: str
    currency: str
    locale: str
    timezone: str
    active: bool
    version: int


class StorePolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    store_id: UUID
    accepting_orders: bool
    max_open_tickets: int
    kds_heartbeat_seconds: int
    printer_fallback_enabled: bool
    version: int


class StoreWithPolicyResponse(BaseModel):
    store: StoreResponse
    policy: StorePolicyResponse


class UpdateStorePolicyRequest(StrictRequestModel):
    accepting_orders: bool
    max_open_tickets: int = Field(ge=1, le=1000)
    kds_heartbeat_seconds: int = Field(ge=5, le=300)
    printer_fallback_enabled: bool = False
    expected_version: int = Field(ge=1)


class HeartbeatResponse(BaseModel):
    resource_id: UUID
    server_time: datetime


class KioskStoreStatusResponse(BaseModel):
    store_id: UUID
    accepting_orders: bool
    currency: str
    locale: str
