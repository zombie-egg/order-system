from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import RefundStatus


class RefundResponse(BaseModel):
    id: UUID
    order_id: UUID
    payment_attempt_id: UUID
    amount_minor: int
    currency: str
    reason_code: str
    status: RefundStatus
    psp_reference: str | None
    failure_code: str | None
    completed_at: datetime | None
    version: int
