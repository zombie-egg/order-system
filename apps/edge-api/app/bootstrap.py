from __future__ import annotations

import secrets
from dataclasses import asdict, dataclass, field

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import FulfillmentEndpointType, PaymentProvider, PermissionCode
from app.core.errors import ConflictError
from app.core.security import hash_device_credential, hash_password
from app.modules.identity.models import (
    Permission,
    Role,
    RolePermission,
    UserAccount,
    UserStoreRole,
)
from app.modules.identity.service import normalize_identifier
from app.modules.organization.models import (
    FulfillmentEndpoint,
    KioskDevice,
    KitchenStation,
    LegalEntity,
    PaymentTerminal,
    Store,
    StoreOperatingPolicy,
    Tenant,
)


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    tenant_id: str
    store_id: str
    owner_user_id: str
    kiosk_id: str
    kiosk_key: str = field(repr=False)
    fulfillment_endpoint_id: str
    fulfillment_endpoint_key: str = field(repr=False)

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


ROLE_PERMISSIONS: dict[str, set[PermissionCode]] = {
    "owner": set(PermissionCode),
    "manager": {
        PermissionCode.ORGANIZATION_READ,
        PermissionCode.ORGANIZATION_WRITE,
        PermissionCode.IDENTITY_READ,
        PermissionCode.CATALOG_READ,
        PermissionCode.CATALOG_WRITE,
        PermissionCode.ORDER_READ,
        PermissionCode.PAYMENT_READ,
        PermissionCode.PAYMENT_RECONCILE,
        PermissionCode.KITCHEN_OPERATE,
        PermissionCode.REVIEW_READ,
        PermissionCode.REVIEW_RESOLVE,
        PermissionCode.REPORT_READ,
        PermissionCode.AUDIT_READ,
    },
    "staff": {
        PermissionCode.CATALOG_READ,
        PermissionCode.ORDER_READ,
        PermissionCode.PAYMENT_READ,
        PermissionCode.KITCHEN_OPERATE,
        PermissionCode.REVIEW_READ,
    },
    "reviewer": {
        PermissionCode.ORDER_READ,
        PermissionCode.PAYMENT_READ,
        PermissionCode.REVIEW_READ,
        PermissionCode.REVIEW_RESOLVE,
        PermissionCode.AUDIT_READ,
    },
}


def _required_text(value: str, *, field_name: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if len(normalized) > max_length:
        raise ValueError(f"{field_name} must contain at most {max_length} characters")
    return normalized


async def bootstrap_store(
    session: AsyncSession,
    settings: Settings,
    *,
    tenant_code: str,
    tenant_name: str,
    legal_entity_code: str,
    legal_entity_name: str,
    store_code: str,
    store_name: str,
    owner_username: str,
    owner_display_name: str,
    owner_password: str,
) -> BootstrapResult:
    normalized_tenant_code = normalize_identifier(
        _required_text(tenant_code, field_name="tenant_code", max_length=50)
    )
    normalized_legal_entity_code = normalize_identifier(
        _required_text(legal_entity_code, field_name="legal_entity_code", max_length=50)
    )
    normalized_store_code = _required_text(
        store_code, field_name="store_code", max_length=40
    ).upper()
    normalized_owner_username = normalize_identifier(
        _required_text(owner_username, field_name="owner_username", max_length=120)
    )
    if len(normalized_tenant_code) > 50:
        raise ValueError("tenant_code normalization exceeds 50 characters")
    if len(normalized_legal_entity_code) > 50:
        raise ValueError("legal_entity_code normalization exceeds 50 characters")
    if len(normalized_store_code) > 40:
        raise ValueError("store_code normalization exceeds 40 characters")
    if len(normalized_owner_username) > 120:
        raise ValueError("owner_username normalization exceeds 120 characters")
    clean_tenant_name = _required_text(tenant_name, field_name="tenant_name", max_length=200)
    clean_legal_entity_name = _required_text(
        legal_entity_name,
        field_name="legal_entity_name",
        max_length=200,
    )
    clean_store_name = _required_text(store_name, field_name="store_name", max_length=200)
    clean_owner_display_name = _required_text(
        owner_display_name,
        field_name="owner_display_name",
        max_length=160,
    )
    if len(owner_password) < 12:
        raise ValueError("owner_password must contain at least 12 characters")

    existing = await session.scalar(select(Tenant).where(Tenant.code == normalized_tenant_code))
    if existing is not None:
        raise ConflictError("tenant_exists", "The tenant code already exists")
    owner_password_hash = hash_password(owner_password)

    tenant = Tenant(code=normalized_tenant_code, name=clean_tenant_name)
    try:
        async with session.begin_nested():
            session.add(tenant)
            await session.flush()
    except IntegrityError as exc:
        raise ConflictError("tenant_exists", "The tenant code already exists") from exc

    legal_entity = LegalEntity(
        tenant_id=tenant.id,
        code=normalized_legal_entity_code,
        name=clean_legal_entity_name,
        country_code=settings.default_country,
    )
    session.add(legal_entity)
    await session.flush()

    store = Store(
        legal_entity_id=legal_entity.id,
        code=normalized_store_code,
        name=clean_store_name,
        country_code=settings.default_country,
        currency=settings.default_currency,
        locale=settings.default_locale,
        timezone=settings.business_timezone,
    )
    session.add(store)
    await session.flush()

    policy = StoreOperatingPolicy(
        store_id=store.id,
        accepting_orders=False,
        kds_heartbeat_seconds=settings.kds_online_window_seconds,
    )
    session.add(policy)

    kiosk_key = secrets.token_urlsafe(32)
    kiosk = KioskDevice(
        store_id=store.id,
        code="KIOSK-01",
        display_name="Customer Kiosk 1",
        credential_hash=hash_device_credential(kiosk_key),
    )
    session.add(kiosk)
    await session.flush()

    station = KitchenStation(
        store_id=store.id,
        code="BAR-01",
        name="Main Bar",
        is_default=True,
    )
    session.add(station)
    await session.flush()

    endpoint_key = secrets.token_urlsafe(32)
    endpoint = FulfillmentEndpoint(
        station_id=station.id,
        endpoint_type=FulfillmentEndpointType.KDS,
        external_reference="KDS-01",
        credential_hash=hash_device_credential(endpoint_key),
    )
    session.add(endpoint)

    terminal: PaymentTerminal | None = None
    if settings.mock_payment_enabled:
        terminal = PaymentTerminal(
            kiosk_id=kiosk.id,
            provider=PaymentProvider.MOCK,
            terminal_reference=f"MOCK-{store.code}-01",
            active=True,
        )
    owner = UserAccount(
        tenant_id=tenant.id,
        username=owner_username.strip(),
        username_normalized=normalized_owner_username,
        display_name=clean_owner_display_name,
        password_hash=owner_password_hash,
    )
    session.add(owner)
    if terminal is not None:
        session.add(terminal)
    await session.flush()

    permissions: dict[PermissionCode, Permission] = {}
    for permission_code in PermissionCode:
        permission = await session.scalar(
            select(Permission).where(Permission.code == permission_code.value)
        )
        if permission is None:
            permission = Permission(
                code=permission_code.value,
                description=permission_code.value.replace(":", " ").replace("_", " ").title(),
            )
            session.add(permission)
            await session.flush()
        permissions[permission_code] = permission

    roles: dict[str, Role] = {}
    for role_code, granted_permissions in ROLE_PERMISSIONS.items():
        role = Role(
            tenant_id=tenant.id,
            code=role_code,
            name=role_code.title(),
            system_role=True,
        )
        session.add(role)
        await session.flush()
        session.add_all(
            RolePermission(role_id=role.id, permission_id=permissions[permission].id)
            for permission in granted_permissions
        )
        roles[role_code] = role
    session.add(UserStoreRole(user_id=owner.id, store_id=store.id, role_id=roles["owner"].id))
    await session.flush()
    return BootstrapResult(
        tenant_id=str(tenant.id),
        store_id=str(store.id),
        owner_user_id=str(owner.id),
        kiosk_id=str(kiosk.id),
        kiosk_key=kiosk_key,
        fulfillment_endpoint_id=str(endpoint.id),
        fulfillment_endpoint_key=endpoint_key,
    )
