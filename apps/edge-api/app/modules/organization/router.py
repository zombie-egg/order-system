from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    KioskDependency,
    Principal,
    SessionDependency,
    SettingsDependency,
    require_permission,
)
from app.core.enums import PermissionCode
from app.core.errors import NotFoundError
from app.modules.organization.models import (
    KioskDevice,
    LegalEntity,
    Store,
    StoreOperatingPolicy,
    Tenant,
)
from app.modules.organization.schemas import (
    BrandingResponse,
    CreatedStoreResponse,
    CreateStoreRequest,
    HeartbeatResponse,
    KdsBoardResponse,
    KioskStoreStatusResponse,
    StoreConnectionResponse,
    StoreDeviceCredentialsResponse,
    StoreManagerResponse,
    StorePolicyResponse,
    StoreResponse,
    StoreWithPolicyResponse,
    UpdateBrandingRequest,
    UpdateKdsBoardRequest,
    UpdateStorePolicyRequest,
    UpdateStoreRequest,
)
from app.modules.organization.service import (
    StoreDeviceCredentials,
    create_store,
    get_store_connection,
    get_store_device_credentials,
    get_store_kds_board,
    get_tenant_branding,
    list_assigned_stores,
    reset_store_device_credentials,
    update_store,
    update_store_kds_board,
    update_store_policy,
    update_tenant_branding,
)
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


def _device_response(
    credentials: StoreDeviceCredentials,
) -> StoreDeviceCredentialsResponse:
    return StoreDeviceCredentialsResponse(
        store_id=credentials.store_id,
        kiosk_id=credentials.kiosk_id,
        kiosk_code=credentials.kiosk_code,
        kiosk_key=credentials.kiosk_key,
        station_id=credentials.station_id,
        endpoint_id=credentials.endpoint_id,
        endpoint_code=credentials.endpoint_code,
        endpoint_key=credentials.endpoint_key,
        terminal_id=credentials.terminal_id,
        terminal_provider=credentials.terminal_provider,
    )


@admin_router.get(
    "/stores",
    response_model=list[StoreWithPolicyResponse],
    operation_id="list_assigned_stores",
)
async def get_stores(
    response: Response,
    session: SessionDependency,
    principal: OrganizationReadPrincipal,
    search: str | None = Query(default=None, max_length=80),
) -> list[StoreWithPolicyResponse]:
    _disable_operational_response_caching(response)
    rows = await list_assigned_stores(session, principal, search)
    return [
        StoreWithPolicyResponse(
            store=StoreResponse.model_validate(store),
            policy=StorePolicyResponse.model_validate(policy),
        )
        for store, policy in rows
    ]


@admin_router.post("/stores", response_model=CreatedStoreResponse, status_code=201)
async def post_store(
    request: CreateStoreRequest,
    response: Response,
    session: SessionDependency,
    settings: SettingsDependency,
    principal: OrganizationWritePrincipal,
) -> CreatedStoreResponse:
    _disable_operational_response_caching(response)
    store, policy, credentials, manager = await create_store(
        session,
        principal,
        name=request.name,
        city=request.city,
        locale=request.locale,
        timezone=request.timezone,
        mock_payment_enabled=settings.mock_payment_enabled,
        manager_display_name=request.manager_display_name,
        manager_username=request.manager_username,
        manager_password=request.manager_password,
    )
    return CreatedStoreResponse(
        store=StoreResponse.model_validate(store),
        policy=StorePolicyResponse.model_validate(policy),
        tenant_code=await _tenant_code_for_store(session, store),
        device_credentials=_device_response(credentials),
        manager_account=StoreManagerResponse(
            user_id=manager.id,
            username=manager.username,
            display_name=manager.display_name,
            active=manager.active,
        ),
    )


async def _tenant_code_for_store(session: AsyncSession, store: Store) -> str:
    legal_entity = await session.get(LegalEntity, store.legal_entity_id)
    if legal_entity is None:
        return ""
    tenant = await session.get(Tenant, legal_entity.tenant_id)
    return tenant.code if tenant is not None else ""


@admin_router.get(
    "/stores/{store_id}/connection",
    response_model=StoreConnectionResponse,
    operation_id="get_store_connection",
)
async def get_store_connection_details(
    store_id: UUID,
    response: Response,
    session: SessionDependency,
    principal: OrganizationWritePrincipal,
) -> StoreConnectionResponse:
    _disable_operational_response_caching(response)
    connection = await get_store_connection(session, principal, store_id)
    return StoreConnectionResponse(
        store_id=connection.store.id,
        store_code=connection.store.code,
        store_name=connection.store.name,
        tenant_code=connection.tenant_code,
        kiosk_id=connection.credentials.kiosk_id,
        kiosk_key=connection.credentials.kiosk_key,
        endpoint_id=connection.credentials.endpoint_id,
        endpoint_key=connection.credentials.endpoint_key,
        managers=[
            StoreManagerResponse(
                user_id=user.id,
                username=user.username,
                display_name=user.display_name,
                active=user.active,
            )
            for user in connection.managers
        ],
    )


@admin_router.get(
    "/stores/{store_id}/device-credentials",
    response_model=StoreDeviceCredentialsResponse,
    operation_id="get_store_device_credentials",
)
async def get_store_devices(
    store_id: UUID,
    response: Response,
    session: SessionDependency,
    principal: OrganizationWritePrincipal,
) -> StoreDeviceCredentialsResponse:
    _disable_operational_response_caching(response)
    credentials = await get_store_device_credentials(session, principal, store_id)
    return _device_response(credentials)


@admin_router.post(
    "/stores/{store_id}/device-credentials/reset",
    response_model=StoreDeviceCredentialsResponse,
    operation_id="reset_store_device_credentials",
)
async def reset_store_devices(
    store_id: UUID,
    response: Response,
    session: SessionDependency,
    settings: SettingsDependency,
    principal: OrganizationWritePrincipal,
) -> StoreDeviceCredentialsResponse:
    _disable_operational_response_caching(response)
    credentials = await reset_store_device_credentials(
        session,
        principal,
        store_id,
        mock_payment_enabled=settings.mock_payment_enabled,
    )
    return _device_response(credentials)


@admin_router.get(
    "/stores/{store_id}/kds-board",
    response_model=KdsBoardResponse,
    operation_id="get_store_kds_board",
)
async def get_kds_board(
    store_id: UUID,
    response: Response,
    session: SessionDependency,
    principal: OrganizationWritePrincipal,
) -> KdsBoardResponse:
    _disable_operational_response_caching(response)
    station = await get_store_kds_board(session, principal, store_id)
    return KdsBoardResponse(
        store_id=station.store_id,
        station_id=station.id,
        code=station.code,
        name=station.name,
        display_title=station.display_title,
        enabled=station.active,
        version=station.version,
    )


@admin_router.patch(
    "/stores/{store_id}/kds-board",
    response_model=KdsBoardResponse,
    operation_id="update_store_kds_board",
)
async def patch_kds_board(
    store_id: UUID,
    request: UpdateKdsBoardRequest,
    response: Response,
    session: SessionDependency,
    principal: OrganizationWritePrincipal,
) -> KdsBoardResponse:
    _disable_operational_response_caching(response)
    station = await update_store_kds_board(
        session,
        principal,
        store_id,
        name=request.name,
        display_title=request.display_title,
        enabled=request.enabled,
        expected_version=request.expected_version,
    )
    return KdsBoardResponse(
        store_id=station.store_id,
        station_id=station.id,
        code=station.code,
        name=station.name,
        display_title=station.display_title,
        enabled=station.active,
        version=station.version,
    )


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
        takeaway_fee_enabled=request.takeaway_fee_enabled,
        takeaway_fee_minor=request.takeaway_fee_minor,
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
        takeaway_fee_enabled=policy.takeaway_fee_enabled,
        takeaway_fee_minor=policy.takeaway_fee_minor,
    )


@admin_router.get(
    "/branding",
    response_model=BrandingResponse,
    operation_id="get_tenant_branding",
)
async def get_branding(
    session: SessionDependency,
    principal: OrganizationReadPrincipal,
) -> BrandingResponse:
    tenant = await get_tenant_branding(session, principal)
    return BrandingResponse(
        merchant_name=tenant.brand_name or tenant.name,
        logo_url=tenant.logo_url,
    )


@admin_router.put(
    "/branding",
    response_model=BrandingResponse,
    operation_id="update_tenant_branding",
)
async def put_branding(
    request: UpdateBrandingRequest,
    session: SessionDependency,
    principal: OrganizationWritePrincipal,
) -> BrandingResponse:
    tenant = await get_tenant_branding(session, principal)
    tenant = await update_tenant_branding(
        session,
        principal,
        tenant,
        merchant_name=request.merchant_name,
        logo_url=request.logo_url,
    )
    return BrandingResponse(
        merchant_name=tenant.brand_name or tenant.name,
        logo_url=tenant.logo_url,
    )


@admin_router.patch(
    "/stores/{store_id}",
    response_model=StoreResponse,
    operation_id="update_store_details",
)
async def patch_store_details(
    store_id: UUID,
    request: UpdateStoreRequest,
    session: SessionDependency,
    principal: OrganizationWritePrincipal,
) -> StoreResponse:
    store = await update_store(
        session,
        principal,
        store_id,
        name=request.name,
        city=request.city,
        expected_version=request.expected_version,
    )
    return StoreResponse.model_validate(store)
