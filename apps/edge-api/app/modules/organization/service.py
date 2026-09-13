from __future__ import annotations

import secrets
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, FulfillmentEndpointType, PaymentProvider
from app.core.errors import ConflictError, NotFoundError
from app.core.principals import Principal
from app.core.security import hash_device_credential, hash_password
from app.modules.audit.service import add_audit_log
from app.modules.identity.models import Role, UserAccount, UserStoreRole
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
class StoreDeviceCredentials:
    """Device identifiers and, when freshly created or rotated, their secrets.

    ``kiosk_key`` / ``endpoint_key`` are only ever populated on creation or on an
    explicit reset. They are never re-derived from the stored one-way hash, so an
    ordinary read cannot leak a previously issued secret.
    """

    store_id: UUID
    kiosk_id: UUID | None
    kiosk_code: str | None
    kiosk_key: str | None
    station_id: UUID | None
    endpoint_id: UUID | None
    endpoint_code: str | None
    endpoint_key: str | None
    terminal_id: UUID | None
    terminal_provider: str | None


async def get_store_for_tenant(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
) -> Store:
    principal.require_store(store_id)
    store = await session.scalar(
        select(Store)
        .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
        .where(
            Store.id == store_id,
            Store.active,
            LegalEntity.active,
            LegalEntity.tenant_id == principal.tenant_id,
        )
    )
    if store is None:
        raise NotFoundError("store", str(store_id))
    return store


async def list_assigned_stores(
    session: AsyncSession,
    principal: Principal,
    search: str | None = None,
) -> list[tuple[Store, StoreOperatingPolicy]]:
    if not principal.store_ids:
        return []
    query = (
        select(Store, StoreOperatingPolicy)
        .join(StoreOperatingPolicy, StoreOperatingPolicy.store_id == Store.id)
        .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
        .where(
            Store.id.in_(principal.store_ids),
            Store.active,
            LegalEntity.active,
            LegalEntity.tenant_id == principal.tenant_id,
        )
    )
    if search and (term := search.strip().casefold()):
        like = f"%{term}%"
        query = query.where(
            func.lower(Store.name).like(like)
            | func.lower(Store.code).like(like)
            | func.lower(func.coalesce(Store.city, "")).like(like)
        )
    rows = (await session.execute(query.order_by(Store.code))).all()
    return [(store, policy) for store, policy in rows]


async def create_store(
    session: AsyncSession,
    principal: Principal,
    *,
    name: str,
    city: str | None,
    locale: str,
    timezone: str,
    mock_payment_enabled: bool,
    manager_display_name: str,
    manager_username: str,
    manager_password: str,
) -> tuple[Store, StoreOperatingPolicy, StoreDeviceCredentials, UserAccount]:
    legal_entity = await session.scalar(
        select(LegalEntity)
        .where(LegalEntity.tenant_id == principal.tenant_id, LegalEntity.active)
        .order_by(LegalEntity.created_at)
    )
    if legal_entity is None:
        raise NotFoundError("legal_entity", str(principal.tenant_id))
    clean_name = name.strip()
    if not clean_name:
        raise ConflictError("store_name_required", "Store name is required")
    if await session.scalar(
        select(Store.id).where(
            Store.legal_entity_id == legal_entity.id,
            func.lower(Store.name) == clean_name.casefold(),
            Store.active,
        )
    ):
        raise ConflictError("store_exists", "A store with this name already exists")
    prefix = "".join(ch for ch in (city or clean_name).upper() if ch.isalpha())[:3] or "STR"
    count = (
        await session.scalar(
            select(func.count(Store.id)).where(Store.legal_entity_id == legal_entity.id)
        )
        or 0
    )
    store = Store(
        legal_entity_id=legal_entity.id,
        code=f"{prefix}-{count + 1:02d}",
        name=clean_name,
        city=(city or "").strip() or None,
        country_code="NL",
        currency="EUR",
        locale=locale,
        timezone=timezone,
    )
    session.add(store)
    await session.flush()
    policy = StoreOperatingPolicy(store_id=store.id)
    session.add(policy)
    await session.flush()
    # A tenant owner who creates a new store administers it, so grant the owner
    # role in the freshly created store. Store-managers/other roles are not
    # auto-granted owner access — admin scoping stays explicit per store.
    owner_role = await session.scalar(
        select(Role).where(Role.tenant_id == principal.tenant_id, Role.code == "owner")
    )
    if owner_role is not None:
        already_owner = await session.scalar(
            select(UserStoreRole.user_id).where(
                UserStoreRole.user_id == principal.user_id,
                UserStoreRole.role_id == owner_role.id,
            )
        )
        if already_owner is not None:
            session.add(
                UserStoreRole(
                    user_id=principal.user_id,
                    store_id=store.id,
                    role_id=owner_role.id,
                )
            )
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=store.id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="organization.store.created",
        target_type="store",
        target_id=store.id,
        after={"code": store.code, "name": store.name},
    )
    # Every store is a fully independent unit of fulfilment: provision its own
    # kiosk device, default kitchen station, KDS end-point and (in mock/demo mode)
    # payment terminal so a freshly created store is immediately usable with the
    # kiosk and a per-store kitchen display.
    credentials = await _ensure_store_devices(
        session,
        store,
        mock_payment_enabled=mock_payment_enabled,
        regenerate=False,
    )
    manager = await _create_manager_for_store(
        session,
        principal.tenant_id,
        store.id,
        display_name=manager_display_name,
        username=manager_username,
        password=manager_password,
    )
    return store, policy, credentials, manager


async def _create_manager_for_store(
    session: AsyncSession,
    tenant_id: UUID,
    store_id: UUID,
    *,
    display_name: str,
    username: str,
    password: str,
) -> UserAccount:
    """Create a store-manager account assigned to a newly created store."""
    normalized = username.strip().casefold()
    if not normalized:
        raise ConflictError("username_required", "Manager username is required")
    manager_role = await session.scalar(
        select(Role)
        .where(Role.tenant_id == tenant_id, Role.code == "manager")
        .with_for_update()
    )
    if manager_role is None:
        raise ConflictError("role_not_found", "The manager role is not configured")
    user = UserAccount(
        tenant_id=tenant_id,
        username=username.strip(),
        username_normalized=normalized,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
            session.add(
                UserStoreRole(
                    user_id=user.id,
                    store_id=store_id,
                    role_id=manager_role.id,
                )
            )
            await session.flush()
    except IntegrityError as exc:
        raise ConflictError("username_exists", "The username already exists") from exc
    add_audit_log(
        session,
        tenant_id=tenant_id,
        store_id=store_id,
        actor_type=ActorType.USER,
        actor_user_id=user.id,
        action="identity.user.created",
        target_type="user_account",
        target_id=user.id,
        after={
            "active": user.active,
            "role_codes": ["manager"],
            "version": user.version,
        },
    )
    return user


async def _ensure_store_devices(
    session: AsyncSession,
    store: Store,
    *,
    mock_payment_enabled: bool,
    regenerate: bool,
) -> StoreDeviceCredentials:
    """Ensure the store has one default kiosk, one kitchen station, one KDS endpoint.

    When ``regenerate`` is true (an explicit credential reset) existing device
    secrets are rotated. Keys are returned only for devices that were created or
    rotated in this call; previously issued keys cannot be recovered from their
    one-way hash and are therefore never returned here.
    """

    station = await session.scalar(
        select(KitchenStation)
        .where(KitchenStation.store_id == store.id, KitchenStation.is_default)
        .order_by(KitchenStation.created_at)
    )
    if station is None:
        station = KitchenStation(
            store_id=store.id,
            code="BAR-01",
            name="Main Bar",
            is_default=True,
        )
        session.add(station)
        await session.flush()

    kiosk = await session.scalar(
        select(KioskDevice).where(
            KioskDevice.store_id == store.id,
            KioskDevice.code == "KIOSK-01",
        )
    )
    kiosk_key: str | None = None
    if kiosk is None:
        kiosk_key = secrets.token_urlsafe(32)
        kiosk = KioskDevice(
            store_id=store.id,
            code="KIOSK-01",
            display_name="Customer Kiosk 1",
            credential_hash=hash_device_credential(kiosk_key),
        )
        session.add(kiosk)
        await session.flush()
    elif regenerate:
        kiosk_key = secrets.token_urlsafe(32)
        kiosk.credential_hash = hash_device_credential(kiosk_key)

    endpoint = await session.scalar(
        select(FulfillmentEndpoint)
        .join(KitchenStation, KitchenStation.id == FulfillmentEndpoint.station_id)
        .where(
            KitchenStation.store_id == store.id,
            FulfillmentEndpoint.endpoint_type == FulfillmentEndpointType.KDS,
        )
        .order_by(FulfillmentEndpoint.created_at)
    )
    endpoint_key: str | None = None
    if endpoint is None:
        endpoint_key = secrets.token_urlsafe(32)
        endpoint = FulfillmentEndpoint(
            station_id=station.id,
            endpoint_type=FulfillmentEndpointType.KDS,
            external_reference="KDS-01",
            credential_hash=hash_device_credential(endpoint_key),
        )
        session.add(endpoint)
        await session.flush()
    elif regenerate:
        endpoint_key = secrets.token_urlsafe(32)
        endpoint.credential_hash = hash_device_credential(endpoint_key)

    terminal = await session.scalar(
        select(PaymentTerminal)
        .join(KioskDevice, KioskDevice.id == PaymentTerminal.kiosk_id)
        .where(KioskDevice.store_id == store.id)
    )
    if terminal is None and mock_payment_enabled:
        terminal = PaymentTerminal(
            kiosk_id=kiosk.id,
            provider=PaymentProvider.MOCK,
            terminal_reference=f"MOCK-{store.code}-01",
            active=True,
        )
        session.add(terminal)
        await session.flush()

    await session.flush()
    return StoreDeviceCredentials(
        store_id=store.id,
        kiosk_id=kiosk.id,
        kiosk_code=kiosk.code,
        kiosk_key=kiosk_key,
        station_id=station.id,
        endpoint_id=endpoint.id,
        endpoint_code=endpoint.external_reference,
        endpoint_key=endpoint_key,
        terminal_id=terminal.id if terminal is not None else None,
        terminal_provider=terminal.provider.value if terminal is not None else None,
    )


async def get_store_device_credentials(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
) -> StoreDeviceCredentials:
    """Read-only view of the devices provisioned for a store (no secrets)."""
    store = await get_store_for_tenant(session, principal, store_id)
    return await _describe_store_devices(session, store)


async def reset_store_device_credentials(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    mock_payment_enabled: bool,
) -> StoreDeviceCredentials:
    """Provision (if missing) and rotate the store's device secrets, returning them once."""
    store = await get_store_for_tenant(session, principal, store_id)
    return await _ensure_store_devices(
        session,
        store,
        mock_payment_enabled=mock_payment_enabled,
        regenerate=True,
    )


async def _describe_store_devices(
    session: AsyncSession,
    store: Store,
) -> StoreDeviceCredentials:
    station = await session.scalar(
        select(KitchenStation)
        .where(KitchenStation.store_id == store.id, KitchenStation.is_default)
        .order_by(KitchenStation.created_at)
    )
    kiosk = await session.scalar(
        select(KioskDevice).where(
            KioskDevice.store_id == store.id,
            KioskDevice.code == "KIOSK-01",
        )
    )
    endpoint: FulfillmentEndpoint | None = None
    if station is not None:
        endpoint = await session.scalar(
            select(FulfillmentEndpoint)
            .join(KitchenStation, KitchenStation.id == FulfillmentEndpoint.station_id)
            .where(
                KitchenStation.store_id == store.id,
                FulfillmentEndpoint.endpoint_type == FulfillmentEndpointType.KDS,
            )
            .order_by(FulfillmentEndpoint.created_at)
        )
    terminal: PaymentTerminal | None = None
    if kiosk is not None:
        terminal = await session.scalar(
            select(PaymentTerminal)
            .join(KioskDevice, KioskDevice.id == PaymentTerminal.kiosk_id)
            .where(KioskDevice.store_id == store.id)
        )
    return StoreDeviceCredentials(
        store_id=store.id,
        kiosk_id=kiosk.id if kiosk is not None else None,
        kiosk_code=kiosk.code if kiosk is not None else None,
        kiosk_key=None,
        station_id=station.id if station is not None else None,
        endpoint_id=endpoint.id if endpoint is not None else None,
        endpoint_code=endpoint.external_reference if endpoint is not None else None,
        endpoint_key=None,
        terminal_id=terminal.id if terminal is not None else None,
        terminal_provider=terminal.provider.value if terminal is not None else None,
    )


@dataclass(frozen=True, slots=True)
class StoreConnection:
    store: Store
    tenant_code: str
    credentials: StoreDeviceCredentials
    managers: list[UserAccount]


async def _list_store_managers(
    session: AsyncSession,
    store: Store,
    tenant_id: UUID,
) -> list[UserAccount]:
    return list(
        (
            await session.scalars(
                select(UserAccount)
                .join(UserStoreRole, UserStoreRole.user_id == UserAccount.id)
                .join(Role, Role.id == UserStoreRole.role_id)
                .where(
                    UserStoreRole.store_id == store.id,
                    UserAccount.tenant_id == tenant_id,
                    Role.tenant_id == tenant_id,
                    Role.code == "manager",
                )
                .order_by(UserAccount.username_normalized)
            )
        ).all()
    )


async def get_store_connection(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
) -> StoreConnection:
    """Bundle everything needed to operate a store: tenant, devices, managers."""
    store = await get_store_for_tenant(session, principal, store_id)
    legal_entity = await session.get(LegalEntity, store.legal_entity_id)
    tenant = await session.get(Tenant, legal_entity.tenant_id) if legal_entity is not None else None
    tenant_code = tenant.code if tenant is not None else ""
    credentials = await _describe_store_devices(session, store)
    managers = await _list_store_managers(
        session,
        store,
        legal_entity.tenant_id if legal_entity is not None else principal.tenant_id,
    )
    return StoreConnection(
        store=store,
        tenant_code=tenant_code,
        credentials=credentials,
        managers=managers,
    )


async def _get_default_station(
    session: AsyncSession,
    store: Store,
) -> KitchenStation | None:
    return await session.scalar(
        select(KitchenStation)
        .where(KitchenStation.store_id == store.id)
        .order_by(KitchenStation.is_default.desc(), KitchenStation.created_at)
    )


async def get_store_kds_board(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
) -> KitchenStation:
    """Return the store's default kitchen-display (KDS) board configuration."""
    store = await get_store_for_tenant(session, principal, store_id)
    station = await _get_default_station(session, store)
    if station is None:
        raise NotFoundError("kitchen_station", str(store_id))
    return station


async def update_store_kds_board(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    name: str | None,
    display_title: str | None,
    enabled: bool | None,
    expected_version: int,
) -> KitchenStation:
    """Update the store's default KDS board configuration (store-scoped)."""
    store = await get_store_for_tenant(session, principal, store_id)
    scoped_station = await session.scalar(
        select(KitchenStation)
        .join(Store, Store.id == KitchenStation.store_id)
        .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
        .where(
            KitchenStation.store_id == store.id,
            Store.active,
            LegalEntity.active,
            LegalEntity.tenant_id == principal.tenant_id,
        )
        .order_by(KitchenStation.is_default.desc(), KitchenStation.created_at)
        .with_for_update()
    )
    if scoped_station is None:
        raise NotFoundError("kitchen_station", str(store_id))
    if scoped_station.version != expected_version:
        raise ConflictError("stale_version", "The KDS board was modified by another request")
    before = {
        "name": scoped_station.name,
        "display_title": scoped_station.display_title,
        "active": scoped_station.active,
        "version": scoped_station.version,
    }
    if name is not None:
        scoped_station.name = name.strip()
    if display_title is not None:
        scoped_station.display_title = display_title.strip() or None
    if enabled is not None:
        scoped_station.active = enabled
    scoped_station.version = scoped_station.version + 1
    await session.flush()
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=store.id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="organization.kds_board.updated",
        target_type="kitchen_station",
        target_id=scoped_station.id,
        before=before,
        after={
            "name": scoped_station.name,
            "display_title": scoped_station.display_title,
            "active": scoped_station.active,
            "version": scoped_station.version,
        },
    )
    return scoped_station


async def update_store_policy(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    accepting_orders: bool,
    max_open_tickets: int,
    kds_heartbeat_seconds: int,
    printer_fallback_enabled: bool,
    takeaway_fee_enabled: bool,
    takeaway_fee_minor: int,
    expected_version: int,
) -> StoreOperatingPolicy:
    principal.require_store(store_id)
    scoped_policy_ids = (
        select(StoreOperatingPolicy.id)
        .join(Store, Store.id == StoreOperatingPolicy.store_id)
        .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
        .where(
            StoreOperatingPolicy.store_id == store_id,
            Store.active,
            LegalEntity.active,
            LegalEntity.tenant_id == principal.tenant_id,
        )
    )
    current_policy = await session.scalar(
        select(StoreOperatingPolicy)
        .where(StoreOperatingPolicy.id.in_(scoped_policy_ids))
        .with_for_update()
    )
    if current_policy is None:
        raise NotFoundError("store_operating_policy", str(store_id))
    if current_policy.version != expected_version:
        raise ConflictError("stale_version", "The store policy was modified by another request")
    before = {
        "accepting_orders": current_policy.accepting_orders,
        "max_open_tickets": current_policy.max_open_tickets,
        "kds_heartbeat_seconds": current_policy.kds_heartbeat_seconds,
        "printer_fallback_enabled": current_policy.printer_fallback_enabled,
        "takeaway_fee_enabled": current_policy.takeaway_fee_enabled,
        "takeaway_fee_minor": current_policy.takeaway_fee_minor,
        "version": current_policy.version,
    }
    policy = await session.scalar(
        update(StoreOperatingPolicy)
        .where(
            StoreOperatingPolicy.id.in_(scoped_policy_ids),
            StoreOperatingPolicy.version == expected_version,
        )
        .values(
            accepting_orders=accepting_orders,
            max_open_tickets=max_open_tickets,
            kds_heartbeat_seconds=kds_heartbeat_seconds,
            printer_fallback_enabled=printer_fallback_enabled,
            takeaway_fee_enabled=takeaway_fee_enabled,
            takeaway_fee_minor=takeaway_fee_minor,
            version=StoreOperatingPolicy.version + 1,
        )
        .returning(StoreOperatingPolicy)
        .execution_options(populate_existing=True)
    )
    if policy is None:
        raise ConflictError("stale_version", "The store policy was modified by another request")
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=store_id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="organization.store_policy.updated",
        target_type="store_operating_policy",
        target_id=policy.id,
        before=before,
        after={
            "accepting_orders": policy.accepting_orders,
            "max_open_tickets": policy.max_open_tickets,
            "kds_heartbeat_seconds": policy.kds_heartbeat_seconds,
            "printer_fallback_enabled": policy.printer_fallback_enabled,
            "takeaway_fee_enabled": policy.takeaway_fee_enabled,
            "takeaway_fee_minor": policy.takeaway_fee_minor,
            "version": policy.version,
        },
    )
    return policy


async def get_tenant_branding(session: AsyncSession, principal: Principal) -> Tenant:
    tenant = await session.scalar(
        select(Tenant).where(Tenant.id == principal.tenant_id, Tenant.active)
    )
    if tenant is None:
        raise NotFoundError("tenant", str(principal.tenant_id))
    return tenant


async def update_tenant_branding(
    session: AsyncSession,
    principal: Principal,
    tenant: Tenant,
    *,
    merchant_name: str | None,
    logo_url: str | None,
) -> Tenant:
    if merchant_name is not None:
        tenant.brand_name = merchant_name.strip()
    if logo_url is not None:
        tenant.logo_url = logo_url.strip()
    await session.flush()
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=None,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="organization.branding.updated",
        target_type="tenant",
        target_id=tenant.id,
        after={
            "brand_name": tenant.brand_name,
            "logo_url": tenant.logo_url,
        },
    )
    return tenant


async def update_store(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    name: str | None,
    city: str | None,
    expected_version: int,
) -> Store:
    store = await get_store_for_tenant(session, principal, store_id)
    if expected_version < 1:
        raise ConflictError("stale_version", "A valid store version is required")
    if store.version != expected_version:
        raise ConflictError("stale_version", "The store was modified by another request")
    before = {"name": store.name, "city": store.city}
    if name is not None:
        store.name = name.strip()
    if city is not None:
        store.city = city.strip() or None
    store.version = store.version + 1
    await session.flush()
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=store.id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="organization.store.updated",
        target_type="store",
        target_id=store.id,
        before=before,
        after={"name": store.name, "city": store.city, "version": store.version},
    )
    return store
