from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select

from app.api.dependencies import (
    KioskDependency,
    Principal,
    SessionDependency,
    require_permission,
)
from app.core.enums import PermissionCode
from app.core.errors import NotFoundError
from app.modules.organization.models import KioskDevice, Store, StoreOperatingPolicy
from app.modules.organization.schemas import (
    HeartbeatResponse,
    KioskStoreStatusResponse,
    StorePolicyResponse,
    StoreResponse,
    StoreWithPolicyResponse,
    UpdateStorePolicyRequest,
)
from app.modules.organization.service import list_assigned_stores, update_store_policy
from app.persistence.base import utc_now

router = APIRouter(tags=["organization"])
admin_router = APIRouter(prefix="/admin/organization", tags=["admin-organization"])

OrganizationReadPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.ORGANIZATION_READ.value))
]
OrganizationWritePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.ORGANIZATION_WRITE.value))
]


def _disable_operational_response_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@admin_router.get(
    "/stores",
    response_model=list[StoreWithPolicyResponse],
    operation_id="list_assigned_stores",
)
async def get_stores(
    response: Response,
    session: SessionDependency,
    principal: OrganizationReadPrincipal,
) -> list[StoreWithPolicyResponse]:
    _disable_operational_response_caching(response)
    rows = await list_assigned_stores(session, principal)
    return [
        StoreWithPolicyResponse(
            store=StoreResponse.model_validate(store),
            policy=StorePolicyResponse.model_validate(policy),
        )
        for store, policy in rows
    ]


@admin_router.patch(
    "/stores/{store_id}/policy",
    response_model=StorePolicyResponse,
    operation_id="update_store_operating_policy",
)
async def patch_store_policy(
    store_id: UUID,
    request: UpdateStorePolicyRequest,
    response: Response,
    session: SessionDependency,
    principal: OrganizationWritePrincipal,
) -> StorePolicyResponse:
    _disable_operational_response_caching(response)
    policy = await update_store_policy(
        session,
        principal,
        store_id,
        accepting_orders=request.accepting_orders,
        max_open_tickets=request.max_open_tickets,
        kds_heartbeat_seconds=request.kds_heartbeat_seconds,
        printer_fallback_enabled=request.printer_fallback_enabled,
        expected_version=request.expected_version,
    )
    return StorePolicyResponse.model_validate(policy)


@router.post(
    "/kiosk/heartbeat",
    response_model=HeartbeatResponse,
    operation_id="record_kiosk_heartbeat",
)
async def kiosk_heartbeat(
    response: Response,
    session: SessionDependency,
    kiosk_principal: KioskDependency,
) -> HeartbeatResponse:
    _disable_operational_response_caching(response)
    kiosk = await session.get(KioskDevice, kiosk_principal.kiosk_id)
    if kiosk is None:
        raise NotFoundError("kiosk_device", str(kiosk_principal.kiosk_id))
    now = utc_now()
    kiosk.last_seen_at = now
    return HeartbeatResponse(resource_id=kiosk.id, server_time=now)


@router.get(
    "/kiosk/store-status",
    response_model=KioskStoreStatusResponse,
    operation_id="get_kiosk_store_status",
)
async def kiosk_store_status(
    response: Response,
    session: SessionDependency,
    kiosk_principal: KioskDependency,
) -> KioskStoreStatusResponse:
    _disable_operational_response_caching(response)
    row = (
        await session.execute(
            select(Store, StoreOperatingPolicy)
            .join(StoreOperatingPolicy, StoreOperatingPolicy.store_id == Store.id)
            .where(Store.id == kiosk_principal.store_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("store", str(kiosk_principal.store_id))
    store, policy = row
    return KioskStoreStatusResponse(
        store_id=store.id,
        accepting_orders=store.active and policy.accepting_orders,
        currency=store.currency,
        locale=store.locale,
    )
