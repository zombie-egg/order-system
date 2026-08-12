from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from app.core.enums import ActorType


class AuditLogResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    store_id: UUID | None
    actor_type: ActorType
    actor_user_id: UUID | None
    actor_device_id: UUID | None
    action: str
    target_type: str
    target_id: UUID
    correlation_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    metadata: dict[str, Any]
    occurred_at: datetime
