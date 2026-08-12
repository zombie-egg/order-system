from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest

import app.persistence.models  # noqa: F401
from app.core.enums import ActorType, PermissionCode
from app.core.principals import Principal
from app.modules.audit.models import AuditLog
from app.modules.audit.service import list_audit_logs
from app.modules.organization.models import LegalEntity, Store, Tenant
from app.persistence.base import Base, utc_now
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def audit_database(anyio_backend: str) -> AsyncIterator[tuple[Database, UUID, UUID, UUID]]:
    del anyio_backend
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    tenant_id = uuid4()
    legal_entity_id = uuid4()
    first_store_id = uuid4()
    second_store_id = uuid4()
    async with database.session_factory() as session, session.begin():
        session.add(Tenant(id=tenant_id, code="audit-tenant", name="Audit Tenant"))
        await session.flush()
        session.add(
            LegalEntity(
                id=legal_entity_id,
                tenant_id=tenant_id,
                code="audit-entity",
                name="Audit Entity",
                country_code="NL",
            )
        )
        await session.flush()
        session.add_all(
            [
                Store(
                    id=first_store_id,
                    legal_entity_id=legal_entity_id,
                    code="AMS-01",
                    name="Amsterdam One",
                    country_code="NL",
                    currency="EUR",
                    locale="nl-NL",
                    timezone="Europe/Amsterdam",
                ),
                Store(
                    id=second_store_id,
                    legal_entity_id=legal_entity_id,
                    code="AMS-02",
                    name="Amsterdam Two",
                    country_code="NL",
                    currency="EUR",
                    locale="nl-NL",
                    timezone="Europe/Amsterdam",
                ),
            ]
        )
        await session.flush()
        session.add_all(
            [
                AuditLog(
                    tenant_id=tenant_id,
                    store_id=None,
                    actor_type=ActorType.SYSTEM,
                    action="tenant.event",
                    target_type="tenant",
                    target_id=tenant_id,
                    metadata_redacted={},
                    occurred_at=utc_now(),
                ),
                AuditLog(
                    tenant_id=tenant_id,
                    store_id=first_store_id,
                    actor_type=ActorType.SYSTEM,
                    action="first-store.event",
                    target_type="store",
                    target_id=first_store_id,
                    metadata_redacted={},
                    occurred_at=utc_now(),
                ),
                AuditLog(
                    tenant_id=tenant_id,
                    store_id=second_store_id,
                    actor_type=ActorType.SYSTEM,
                    action="second-store.event",
                    target_type="store",
                    target_id=second_store_id,
                    metadata_redacted={},
                    occurred_at=utc_now(),
                ),
            ]
        )
    try:
        yield database, tenant_id, first_store_id, second_store_id
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_tenant_audit_reader_can_see_tenant_and_all_store_events(
    audit_database: tuple[Database, UUID, UUID, UUID],
) -> None:
    database, tenant_id, first_store_id, _ = audit_database
    principal = Principal(
        user_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset(
            {PermissionCode.AUDIT_READ.value, PermissionCode.AUDIT_TENANT_READ.value}
        ),
        store_ids=frozenset({first_store_id}),
    )

    async with database.session_factory() as session:
        logs = await list_audit_logs(session, principal, limit=100)

    assert {log.action for log in logs} == {
        "tenant.event",
        "first-store.event",
        "second-store.event",
    }


@pytest.mark.anyio
async def test_store_audit_reader_is_limited_to_assigned_store_events(
    audit_database: tuple[Database, UUID, UUID, UUID],
) -> None:
    database, tenant_id, first_store_id, _ = audit_database
    principal = Principal(
        user_id=uuid4(),
        tenant_id=tenant_id,
        permissions=frozenset({PermissionCode.AUDIT_READ.value}),
        store_ids=frozenset({first_store_id}),
    )

    async with database.session_factory() as session:
        logs = await list_audit_logs(session, principal, limit=100)

    assert [log.action for log in logs] == ["first-store.event"]
