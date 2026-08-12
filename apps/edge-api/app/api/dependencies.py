from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated, cast
from uuid import UUID

from fastapi import Depends, Request, Security
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import UnauthorizedError
from app.core.principals import FulfillmentEndpointPrincipal, KioskPrincipal
from app.core.principals import Principal as Principal
from app.core.security import TokenValidationError, decode_access_token, verify_device_credential
from app.modules.identity.models import (
    Permission,
    Role,
    RolePermission,
    UserAccount,
    UserStoreRole,
)
from app.modules.organization.models import (
    FulfillmentEndpoint,
    KioskDevice,
    KitchenStation,
    LegalEntity,
    Store,
    Tenant,
)
from app.persistence.database import Database

bearer_scheme = HTTPBearer(
    auto_error=False,
    scheme_name="StaffBearerAuth",
    description="Short-lived staff access token. Permissions are reloaded from the database.",
)
kiosk_id_scheme = APIKeyHeader(
    name="X-Kiosk-ID",
    auto_error=False,
    scheme_name="KioskDeviceId",
    description="Provisioned kiosk device identifier.",
)
kiosk_key_scheme = APIKeyHeader(
    name="X-Kiosk-Key",
    auto_error=False,
    scheme_name="KioskDeviceKey",
    description="Provisioned high-entropy kiosk device secret.",
)
fulfillment_endpoint_id_scheme = APIKeyHeader(
    name="X-Endpoint-ID",
    auto_error=False,
    scheme_name="FulfillmentEndpointId",
    description="Provisioned fulfillment endpoint identifier.",
)
fulfillment_endpoint_key_scheme = APIKeyHeader(
    name="X-Endpoint-Key",
    auto_error=False,
    scheme_name="FulfillmentEndpointKey",
    description="Provisioned high-entropy fulfillment endpoint secret.",
)
_INVALID_DEVICE_CREDENTIAL_HASH = "0" * 64


def get_database(request: Request) -> Database:
    return cast(Database, request.app.state.database)


def get_request_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


async def get_session(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncSession]:
    async with database.session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: Annotated[Settings, Depends(get_request_settings)],
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    try:
        claims = decode_access_token(
            credentials.credentials,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
        )
        user_id = UUID(claims.subject)
        tenant_id = UUID(claims.tenant_id)
    except (TokenValidationError, ValueError) as exc:
        raise UnauthorizedError("Access token is invalid or expired") from exc

    user = await session.scalar(
        select(UserAccount)
        .join(Tenant, Tenant.id == UserAccount.tenant_id)
        .where(
            UserAccount.id == user_id,
            UserAccount.tenant_id == tenant_id,
            UserAccount.active,
            Tenant.active,
        )
    )
    if user is None or user.token_version != claims.token_version:
        raise UnauthorizedError("The user account or token is no longer valid")

    assignments = (
        await session.execute(
            select(UserStoreRole.store_id, Permission.code)
            .join(Role, Role.id == UserStoreRole.role_id)
            .join(Store, Store.id == UserStoreRole.store_id)
            .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
            .outerjoin(RolePermission, RolePermission.role_id == UserStoreRole.role_id)
            .outerjoin(Permission, Permission.id == RolePermission.permission_id)
            .where(
                UserStoreRole.user_id == user.id,
                Role.tenant_id == user.tenant_id,
                LegalEntity.tenant_id == user.tenant_id,
                LegalEntity.active,
                Store.active,
            )
        )
    ).all()

    store_ids: set[UUID] = set()
    permission_stores: dict[str, set[UUID]] = {}
    for store_id, permission in assignments:
        store_ids.add(store_id)
        if permission is not None:
            permission_stores.setdefault(permission, set()).add(store_id)
    permissions = frozenset(permission_stores)
    permission_store_ids = tuple(
        (permission, frozenset(scoped_store_ids))
        for permission, scoped_store_ids in sorted(permission_stores.items())
    )
    return Principal(
        user_id=user.id,
        tenant_id=user.tenant_id,
        permissions=permissions,
        store_ids=frozenset(store_ids),
        permission_store_ids=permission_store_ids,
    )


def require_permission(permission: str) -> Callable[..., Awaitable[Principal]]:
    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        return principal.scope_to_permission(permission)

    return dependency


async def get_kiosk_principal(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    kiosk_id: Annotated[str | None, Security(kiosk_id_scheme)],
    kiosk_key: Annotated[str | None, Security(kiosk_key_scheme)],
) -> KioskPrincipal:
    if not kiosk_id or not kiosk_key:
        raise UnauthorizedError("Kiosk credentials are required", authenticate_header=None)
    try:
        parsed_id = UUID(kiosk_id)
    except ValueError as exc:
        raise UnauthorizedError("Kiosk credentials are invalid", authenticate_header=None) from exc
    kiosk = await session.scalar(
        select(KioskDevice)
        .join(Store, Store.id == KioskDevice.store_id)
        .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
        .join(Tenant, Tenant.id == LegalEntity.tenant_id)
        .where(
            KioskDevice.id == parsed_id,
            KioskDevice.active,
            Store.active,
            LegalEntity.active,
            Tenant.active,
        )
    )
    credential_valid = verify_device_credential(
        kiosk_key,
        kiosk.credential_hash if kiosk is not None else _INVALID_DEVICE_CREDENTIAL_HASH,
    )
    if kiosk is None or not credential_valid:
        raise UnauthorizedError("Kiosk credentials are invalid", authenticate_header=None)
    return KioskPrincipal(kiosk_id=kiosk.id, store_id=kiosk.store_id)


async def get_fulfillment_endpoint_principal(
    session: Annotated[AsyncSession, Depends(get_session, scope="function")],
    endpoint_id: Annotated[str | None, Security(fulfillment_endpoint_id_scheme)],
    endpoint_key: Annotated[str | None, Security(fulfillment_endpoint_key_scheme)],
) -> FulfillmentEndpointPrincipal:
    if not endpoint_id or not endpoint_key:
        raise UnauthorizedError(
            "Fulfillment endpoint credentials are required", authenticate_header=None
        )
    try:
        parsed_id = UUID(endpoint_id)
    except ValueError as exc:
        raise UnauthorizedError(
            "Fulfillment endpoint credentials are invalid", authenticate_header=None
        ) from exc
    endpoint = await session.scalar(
        select(FulfillmentEndpoint)
        .join(KitchenStation, KitchenStation.id == FulfillmentEndpoint.station_id)
        .join(Store, Store.id == KitchenStation.store_id)
        .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
        .join(Tenant, Tenant.id == LegalEntity.tenant_id)
        .where(
            FulfillmentEndpoint.id == parsed_id,
            FulfillmentEndpoint.active,
            KitchenStation.active,
            Store.active,
            LegalEntity.active,
            Tenant.active,
        )
    )
    credential_valid = verify_device_credential(
        endpoint_key,
        endpoint.credential_hash if endpoint is not None else _INVALID_DEVICE_CREDENTIAL_HASH,
    )
    if endpoint is None or not credential_valid:
        raise UnauthorizedError(
            "Fulfillment endpoint credentials are invalid", authenticate_header=None
        )
    return FulfillmentEndpointPrincipal(
        endpoint_id=endpoint.id,
        station_id=endpoint.station_id,
    )


SessionDependency = Annotated[AsyncSession, Depends(get_session, scope="function")]
SettingsDependency = Annotated[Settings, Depends(get_request_settings)]
CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
KioskDependency = Annotated[KioskPrincipal, Depends(get_kiosk_principal)]
FulfillmentEndpointDependency = Annotated[
    FulfillmentEndpointPrincipal, Depends(get_fulfillment_endpoint_principal)
]
