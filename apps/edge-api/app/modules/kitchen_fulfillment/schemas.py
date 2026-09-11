from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.api_models import StrictRequestModel
from app.core.enums import FulfillmentFailureReason, FulfillmentStatus, FulfillmentType
from app.core.sensitive_data import contains_sensitive_card_data


class FulfillmentHeartbeatResponse(BaseModel):
    endpoint_id: UUID
    station_id: UUID
    heartbeat_at: datetime
    version: int


class FulfillmentTicketItemResponse(BaseModel):
    order_item_id: UUID
    quantity: int
    name: str
    preparation_snapshot: dict[str, Any]
    allergen_snapshot: dict[str, Any]
    options: list[str] = Field(default_factory=list)


class FulfillmentTicketResponse(BaseModel):
    id: UUID
    order_id: UUID
    station_id: UUID
    source_ticket_id: UUID | None
    generation_number: int
    display_number: str
    status: FulfillmentStatus
    priority: int
    fulfillment_type: FulfillmentType
    failure_reason_code: FulfillmentFailureReason | None
    failure_detail: str | None
    acknowledged_at: datetime | None
    started_at: datetime | None
    ready_at: datetime | None
    collected_at: datetime | None
    version: int
    items: list[FulfillmentTicketItemResponse]


class TransitionTicketRequest(StrictRequestModel):
    to_status: FulfillmentStatus
    expected_version: int = Field(ge=1)
    failure_reason_code: FulfillmentFailureReason | None = None
    failure_detail: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_failure_reason(self) -> TransitionTicketRequest:
        if self.to_status == FulfillmentStatus.UNFULFILLABLE and self.failure_reason_code is None:
            raise ValueError("failure_reason_code is required for UNFULFILLABLE")
        if (
            self.to_status != FulfillmentStatus.UNFULFILLABLE
            and self.failure_reason_code is not None
        ):
            raise ValueError("failure_reason_code is only valid for UNFULFILLABLE")
        if self.to_status != FulfillmentStatus.UNFULFILLABLE and self.failure_detail is not None:
            raise ValueError("failure_detail is only valid for UNFULFILLABLE")
        if self.failure_detail and contains_sensitive_card_data(self.failure_detail):
            raise ValueError("failure_detail must not contain cardholder authentication data")
        return self
