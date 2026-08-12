from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.core.api_models import StrictRequestModel
from app.core.enums import FulfillmentFailureReason, ReviewResolution, ReviewStatus
from app.core.sensitive_data import contains_sensitive_card_data

MAX_REVIEW_PAYLOAD_BYTES = 32_768


class ManualReviewResponse(BaseModel):
    id: UUID
    store_id: UUID
    order_id: UUID
    fulfillment_ticket_id: UUID | None
    case_number: str
    status: ReviewStatus
    reason_code: FulfillmentFailureReason
    priority: int
    assigned_to: UUID | None
    resolution_code: ReviewResolution | None
    assigned_at: datetime | None
    resolved_at: datetime | None
    closed_at: datetime | None
    version: int


class AssignReviewRequest(StrictRequestModel):
    expected_version: int = Field(ge=1)
    assignee_user_id: UUID | None = None


class ResolveReviewRequest(StrictRequestModel):
    expected_version: int = Field(ge=1)
    resolution: ReviewResolution
    refund_amount_minor: int | None = Field(default=None, gt=0)
    notes: str = Field(default="", max_length=2000)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_resolution_payload(self) -> ResolveReviewRequest:
        if self.resolution == ReviewResolution.PARTIAL_REFUND:
            if self.refund_amount_minor is None:
                raise ValueError("refund_amount_minor is required for a partial refund")
        elif self.refund_amount_minor is not None:
            raise ValueError("refund_amount_minor is only valid for a partial refund")
        try:
            payload_size = len(
                json.dumps(
                    self.payload,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("payload must be JSON serializable") from exc
        if payload_size > MAX_REVIEW_PAYLOAD_BYTES:
            raise ValueError(f"payload must not exceed {MAX_REVIEW_PAYLOAD_BYTES} UTF-8 bytes")
        if contains_sensitive_card_data({"notes": self.notes, "payload": self.payload}):
            raise ValueError("review details must not contain cardholder authentication data")
        return self
