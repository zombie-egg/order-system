from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import Principal, SessionDependency, require_permission
from app.core.enums import PermissionCode
from app.modules.audit.schemas import AuditLogResponse
from app.modules.audit.service import list_audit_logs

router = APIRouter(prefix="/admin/audit", tags=["admin-audit"])

AuditPrincipal = Annotated[Principal, Depends(require_permission(PermissionCode.AUDIT_READ.value))]


@router.get("", response_model=list[AuditLogResponse], operation_id="list_audit_logs")
async def get_audit_logs(
    session: SessionDependency,
    principal: AuditPrincipal,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditLogResponse]:
    logs = await list_audit_logs(session, principal, limit=limit)
    return [
        AuditLogResponse(
            id=log.id,
            tenant_id=log.tenant_id,
            store_id=log.store_id,
            actor_type=log.actor_type,
            actor_user_id=log.actor_user_id,
            actor_device_id=log.actor_device_id,
            action=log.action,
            target_type=log.target_type,
            target_id=log.target_id,
            correlation_id=log.correlation_id,
            before=log.before_redacted,
            after=log.after_redacted,
            metadata=log.metadata_redacted,
            occurred_at=log.occurred_at,
        )
        for log in logs
    ]
