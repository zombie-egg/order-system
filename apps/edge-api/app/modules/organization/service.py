from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType
from app.core.errors import ConflictError, NotFoundError
from app.core.principals import Principal
from app.modules.audit.service import add_audit_log
from app.modules.organization.models import LegalEntity, Store, StoreOperatingPolicy


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
) -> list[tuple[Store, StoreOperatingPolicy]]:
    if not principal.store_ids:
        return []
    rows = (
        await session.execute(
            select(Store, StoreOperatingPolicy)
            .join(StoreOperatingPolicy, StoreOperatingPolicy.store_id == Store.id)
            .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
            .where(
                Store.id.in_(principal.store_ids),
                Store.active,
                LegalEntity.active,
                LegalEntity.tenant_id == principal.tenant_id,
            )
            .order_by(Store.code)
        )
    ).all()
    return [(store, policy) for store, policy in rows]


async def update_store_policy(
    session: AsyncSession,
    principal: Principal,
    store_id: UUID,
    *,
    accepting_orders: bool,
    max_open_tickets: int,
    kds_heartbeat_seconds: int,
    printer_fallback_enabled: bool,
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
            "version": policy.version,
        },
    )
    return policy
