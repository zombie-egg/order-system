from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

import app.persistence.models  # noqa: F401
from app.bootstrap import BootstrapResult, bootstrap_store
from app.core.config import Settings
from app.core.enums import ActorType
from app.core.errors import ConflictError
from app.core.security import (
    create_access_token,
    hash_password,
    verify_device_credential,
    verify_password,
)
from app.main import create_app
from app.modules.audit.models import AuditLog
from app.modules.identity.models import (
    LoginThrottle,
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
    PaymentTerminal,
    Store,
    StoreOperatingPolicy,
    Tenant,
)
from app.persistence.base import Base, utc_now
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass(frozen=True, slots=True)
class SecurityHarness:
    database: Database
    settings: Settings
    bootstrap: BootstrapResult
    client: AsyncClient


async def _bootstrap(database: Database, settings: Settings) -> BootstrapResult:
    async with database.session_factory() as session, session.begin():
        return await bootstrap_store(
            session,
            settings,
            tenant_code="acme-nl",
            tenant_name="ACME Netherlands",
            legal_entity_code="acme-retail-nl",
            legal_entity_name="ACME Retail Nederland B.V.",
            store_code="AMS-01",
            store_name="Amsterdam Central",
            owner_username="owner",
            owner_display_name="Store Owner",
            owner_password="correct horse battery staple",
        )


@pytest.fixture
async def security_harness(anyio_backend: str) -> AsyncIterator[SecurityHarness]:
    del anyio_backend
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="phase-3-test-secret-that-is-at-least-thirty-two-bytes",
        access_token_minutes=5,
        login_max_failures=3,
        login_failure_window_seconds=60,
        login_lockout_seconds=30,
        login_password_verify_concurrency=2,
    )
    result = await _bootstrap(database, settings)
    application = create_app(settings=settings, database=database)
    transport = ASGITransport(app=application)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield SecurityHarness(
            database=database,
            settings=settings,
            bootstrap=result,
            client=client,
        )
    await database.dispose()


async def _login(
    harness: SecurityHarness,
    *,
    username: str = "owner",
    password: str = "correct horse battery staple",
    tenant_code: str = "acme-nl",
) -> str:
    response = await harness.client.post(
        "/api/v1/auth/token",
        json={
            "tenant_code": tenant_code,
            "username": username,
            "password": password,
        },
    )
    assert response.status_code == 200, response.text
    return str(response.json()["access_token"])


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _create_staff_user(harness: SecurityHarness, owner_token: str) -> dict[str, object]:
    response = await harness.client.post(
        "/api/v1/admin/users",
        headers=_bearer(owner_token),
        json={
            "store_id": harness.bootstrap.store_id,
            "username": "barista",
            "display_name": "Barista",
            "password": "barista-password-123",
            "role_codes": ["staff"],
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.mark.anyio
async def test_identity_login_success_and_failure_use_argon2id(
    security_harness: SecurityHarness,
) -> None:
    successful = await security_harness.client.post(
        "/api/v1/auth/token",
        json={
            "tenant_code": " ACME-NL ",
            "username": " OWNER ",
            "password": "correct horse battery staple",
        },
    )
    assert successful.status_code == 200
    assert successful.json()["token_type"] == "bearer"
    assert successful.headers["cache-control"] == "no-store"
    assert successful.headers["pragma"] == "no-cache"

    me = await security_harness.client.get(
        "/api/v1/auth/me",
        headers=_bearer(str(successful.json()["access_token"])),
    )
    assert me.status_code == 200
    assert me.json()["user_id"] == security_harness.bootstrap.owner_user_id
    assert me.json()["store_ids"] == [security_harness.bootstrap.store_id]

    async with security_harness.database.session_factory() as session:
        owner = await session.get(UserAccount, UUID(security_harness.bootstrap.owner_user_id))
        assert owner is not None
        assert owner.password_hash.startswith("$argon2id$v=19$")
        assert verify_password("correct horse battery staple", owner.password_hash)
        assert not verify_password("wrong password", owner.password_hash)
        assert owner.last_login_at is not None

    for payload in (
        {
            "tenant_code": "acme-nl",
            "username": "owner",
            "password": "wrong password",
        },
        {
            "tenant_code": "unknown-tenant",
            "username": "owner",
            "password": "wrong password",
        },
    ):
        failed = await security_harness.client.post("/api/v1/auth/token", json=payload)
        assert failed.status_code == 401
        assert failed.json()["detail"] == "Username or password is incorrect"
        assert "www-authenticate" not in failed.headers


@pytest.mark.anyio
async def test_inactive_tenant_rejects_staff_login(
    security_harness: SecurityHarness,
) -> None:
    async with security_harness.database.session_factory() as session, session.begin():
        tenant = await session.get(Tenant, UUID(security_harness.bootstrap.tenant_id))
        assert tenant is not None
        tenant.active = False

    response = await security_harness.client.post(
        "/api/v1/auth/token",
        json={
            "tenant_code": "acme-nl",
            "username": "owner",
            "password": "correct horse battery staple",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Username or password is incorrect"
    assert "www-authenticate" not in response.headers


@pytest.mark.anyio
async def test_login_throttle_persists_lockout_without_storing_identifiers(
    security_harness: SecurityHarness,
) -> None:
    payload = {
        "tenant_code": "acme-nl",
        "username": "owner",
        "password": "wrong password",
    }
    for expected_status in (401, 401, 429):
        response = await security_harness.client.post("/api/v1/auth/token", json=payload)
        assert response.status_code == expected_status

    assert response.json()["title"] == "too_many_requests"
    assert 1 <= int(response.headers["retry-after"]) <= 30
    assert "www-authenticate" not in response.headers

    blocked_correct_password = await security_harness.client.post(
        "/api/v1/auth/token",
        json={**payload, "password": "correct horse battery staple"},
    )
    assert blocked_correct_password.status_code == 429
    assert 1 <= int(blocked_correct_password.headers["retry-after"]) <= 30

    async with security_harness.database.session_factory() as session, session.begin():
        throttle = await session.scalar(select(LoginThrottle))
        assert throttle is not None
        assert throttle.failed_attempts == 3
        assert throttle.locked_until is not None
        assert len(throttle.principal_key) == 64
        assert "owner" not in throttle.principal_key
        assert "acme" not in throttle.principal_key
        throttle.locked_until = utc_now() - timedelta(seconds=1)

    successful = await security_harness.client.post(
        "/api/v1/auth/token",
        json={**payload, "password": "correct horse battery staple"},
    )
    assert successful.status_code == 200
    async with security_harness.database.session_factory() as session:
        assert await session.scalar(select(func.count(LoginThrottle.principal_key))) == 0


@pytest.mark.anyio
async def test_identity_disabled_account_rejects_login_and_existing_token(
    security_harness: SecurityHarness,
) -> None:
    owner_token = await _login(security_harness)
    created = await _create_staff_user(security_harness, owner_token)
    assert created["version"] == 1
    staff_token = await _login(
        security_harness,
        username="barista",
        password="barista-password-123",
    )

    disabled = await security_harness.client.patch(
        f"/api/v1/admin/users/{created['id']}/status",
        headers=_bearer(owner_token),
        json={"active": False, "expected_version": 1},
    )
    assert disabled.status_code == 200
    assert disabled.json()["active"] is False
    assert disabled.json()["token_version"] == 2
    assert disabled.json()["version"] == 2

    stale_update = await security_harness.client.patch(
        f"/api/v1/admin/users/{created['id']}/status",
        headers=_bearer(owner_token),
        json={"active": True, "expected_version": 1},
    )
    assert stale_update.status_code == 409
    assert stale_update.json()["title"] == "stale_version"

    old_token_response = await security_harness.client.get(
        "/api/v1/auth/me",
        headers=_bearer(staff_token),
    )
    assert old_token_response.status_code == 401

    disabled_login = await security_harness.client.post(
        "/api/v1/auth/token",
        json={
            "tenant_code": "acme-nl",
            "username": "barista",
            "password": "barista-password-123",
        },
    )
    assert disabled_login.status_code == 401


@pytest.mark.anyio
async def test_identity_token_version_change_invalidates_existing_token(
    security_harness: SecurityHarness,
) -> None:
    token = await _login(security_harness)
    async with security_harness.database.session_factory() as session, session.begin():
        owner = await session.get(UserAccount, UUID(security_harness.bootstrap.owner_user_id))
        assert owner is not None
        owner.token_version += 1

    response = await security_harness.client.get(
        "/api/v1/auth/me",
        headers=_bearer(token),
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.anyio
async def test_identity_expired_and_tampered_tokens_are_rejected(
    security_harness: SecurityHarness,
) -> None:
    expired_token, _ = create_access_token(
        subject=security_harness.bootstrap.owner_user_id,
        tenant_id=security_harness.bootstrap.tenant_id,
        token_version=1,
        permissions={"organization:read"},
        secret=security_harness.settings.jwt_secret,
        issuer=security_harness.settings.jwt_issuer,
        audience=security_harness.settings.jwt_audience,
        lifetime=timedelta(minutes=1),
        now=datetime.now(UTC) - timedelta(minutes=2),
    )
    expired = await security_harness.client.get(
        "/api/v1/auth/me",
        headers=_bearer(expired_token),
    )
    assert expired.status_code == 401

    valid_token = await _login(security_harness)
    header, payload, signature = valid_token.split(".")
    middle = len(signature) // 2
    replacement = "A" if signature[middle] != "A" else "B"
    tampered_token = (
        f"{header}.{payload}.{signature[:middle]}{replacement}{signature[middle + 1 :]}"
    )
    tampered = await security_harness.client.get(
        "/api/v1/auth/me",
        headers=_bearer(tampered_token),
    )
    assert tampered.status_code == 401


@pytest.mark.anyio
async def test_identity_permission_denial_is_forbidden(
    security_harness: SecurityHarness,
) -> None:
    owner_token = await _login(security_harness)
    await _create_staff_user(security_harness, owner_token)
    staff_token = await _login(
        security_harness,
        username="barista",
        password="barista-password-123",
    )

    response = await security_harness.client.get(
        "/api/v1/admin/organization/stores",
        headers=_bearer(staff_token),
    )
    assert response.status_code == 403
    assert response.json()["title"] == "forbidden"


@pytest.mark.anyio
async def test_identity_delegated_admin_cannot_grant_permissions_it_lacks(
    security_harness: SecurityHarness,
) -> None:
    tenant_id = UUID(security_harness.bootstrap.tenant_id)
    store_id = UUID(security_harness.bootstrap.store_id)
    async with security_harness.database.session_factory() as session, session.begin():
        identity_write = await session.scalar(
            select(Permission).where(Permission.code == "identity:write")
        )
        assert identity_write is not None
        delegated_role = Role(
            tenant_id=tenant_id,
            code="delegated-identity-admin",
            name="Delegated Identity Admin",
        )
        delegated_user = UserAccount(
            tenant_id=tenant_id,
            username="delegated-admin",
            username_normalized="delegated-admin",
            display_name="Delegated Admin",
            password_hash=hash_password("delegated-admin-password-123"),
        )
        session.add_all([delegated_role, delegated_user])
        await session.flush()
        session.add_all(
            [
                RolePermission(
                    role_id=delegated_role.id,
                    permission_id=identity_write.id,
                ),
                UserStoreRole(
                    user_id=delegated_user.id,
                    store_id=store_id,
                    role_id=delegated_role.id,
                ),
            ]
        )

    delegated_token = await _login(
        security_harness,
        username="delegated-admin",
        password="delegated-admin-password-123",
    )
    response = await security_harness.client.post(
        "/api/v1/admin/users",
        headers=_bearer(delegated_token),
        json={
            "store_id": str(store_id),
            "username": "promoted-user",
            "display_name": "Promoted User",
            "password": "promoted-user-password-123",
            "role_codes": ["owner"],
        },
    )

    assert response.status_code == 403
    assert response.json()["title"] == "forbidden"
    async with security_harness.database.session_factory() as session:
        promoted_user = await session.scalar(
            select(UserAccount).where(
                UserAccount.tenant_id == tenant_id,
                UserAccount.username_normalized == "promoted-user",
            )
        )
        assert promoted_user is None


@pytest.mark.anyio
async def test_identity_and_store_policy_mutations_append_redacted_user_audits(
    security_harness: SecurityHarness,
) -> None:
    owner_token = await _login(security_harness)
    created = await _create_staff_user(security_harness, owner_token)
    disabled = await security_harness.client.patch(
        f"/api/v1/admin/users/{created['id']}/status",
        headers=_bearer(owner_token),
        json={"active": False, "expected_version": 1},
    )
    assert disabled.status_code == 200
    policy_updated = await security_harness.client.patch(
        f"/api/v1/admin/organization/stores/{security_harness.bootstrap.store_id}/policy",
        headers=_bearer(owner_token),
        json={
            "accepting_orders": True,
            "max_open_tickets": 50,
            "kds_heartbeat_seconds": 30,
            "printer_fallback_enabled": False,
            "expected_version": 1,
        },
    )
    assert policy_updated.status_code == 200

    expected_actions = {
        "identity.user.created",
        "identity.user.status_changed",
        "organization.store_policy.updated",
    }
    async with security_harness.database.session_factory() as session:
        logs = list(
            (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.action.in_(expected_actions))
                    .order_by(AuditLog.occurred_at)
                )
            ).all()
        )
    assert {log.action for log in logs} == expected_actions
    assert len(logs) == 3
    assert all(log.actor_type == ActorType.USER for log in logs)
    assert all(str(log.actor_user_id) == security_harness.bootstrap.owner_user_id for log in logs)
    assert all(str(log.store_id) == security_harness.bootstrap.store_id for log in logs)

    by_action = {log.action: log for log in logs}
    created_audit = by_action["identity.user.created"]
    assert str(created_audit.target_id) == str(created["id"])
    assert created_audit.before_redacted is None
    assert created_audit.after_redacted == {
        "active": True,
        "role_codes": ["staff"],
        "version": 1,
    }
    status_audit = by_action["identity.user.status_changed"]
    assert status_audit.before_redacted == {
        "active": True,
        "token_version": 1,
        "version": 1,
    }
    assert status_audit.after_redacted == {
        "active": False,
        "token_version": 2,
        "version": 2,
    }
    policy_audit = by_action["organization.store_policy.updated"]
    assert policy_audit.after_redacted == {
        "accepting_orders": True,
        "max_open_tickets": 50,
        "kds_heartbeat_seconds": 30,
            "printer_fallback_enabled": False,
            "takeaway_fee_enabled": False,
            "takeaway_fee_minor": 0,
            "version": 2,
    }

    serialized_audits = json.dumps(
        [
            {
                "before": log.before_redacted,
                "after": log.after_redacted,
                "metadata": log.metadata_redacted,
            }
            for log in logs
        ],
        default=str,
        sort_keys=True,
    )
    assert "barista-password-123" not in serialized_audits
    assert "password_hash" not in serialized_audits
    assert "$argon2" not in serialized_audits
    assert security_harness.bootstrap.kiosk_key not in serialized_audits
    assert security_harness.bootstrap.fulfillment_endpoint_key not in serialized_audits


@pytest.mark.anyio
async def test_identity_database_rbac_changes_override_stale_token_claims(
    security_harness: SecurityHarness,
) -> None:
    token = await _login(security_harness)
    tenant_id = UUID(security_harness.bootstrap.tenant_id)
    async with security_harness.database.session_factory() as session, session.begin():
        owner_role_id = await session.scalar(
            select(Role.id).where(Role.tenant_id == tenant_id, Role.code == "owner")
        )
        permission_id = await session.scalar(
            select(Permission.id).where(Permission.code == "organization:read")
        )
        assert owner_role_id is not None and permission_id is not None
        await session.execute(
            delete(RolePermission).where(
                RolePermission.role_id == owner_role_id,
                RolePermission.permission_id == permission_id,
            )
        )

    response = await security_harness.client.get(
        "/api/v1/admin/organization/stores",
        headers=_bearer(token),
    )
    assert response.status_code == 403


@pytest.mark.anyio
async def test_identity_permission_is_scoped_to_the_granting_store(
    security_harness: SecurityHarness,
) -> None:
    first_store_id = UUID(security_harness.bootstrap.store_id)
    owner_id = UUID(security_harness.bootstrap.owner_user_id)
    tenant_id = UUID(security_harness.bootstrap.tenant_id)
    async with security_harness.database.session_factory() as session, session.begin():
        first_store = await session.get(Store, first_store_id)
        assert first_store is not None
        staff_role = await session.scalar(
            select(Role).where(Role.tenant_id == tenant_id, Role.code == "staff")
        )
        assert staff_role is not None
        second_store = Store(
            legal_entity_id=first_store.legal_entity_id,
            code="AMS-02",
            name="Amsterdam West",
            country_code="NL",
            currency="EUR",
            locale="nl-NL",
            timezone="Europe/Amsterdam",
        )
        session.add(second_store)
        await session.flush()
        session.add_all(
            [
                StoreOperatingPolicy(store_id=second_store.id),
                UserStoreRole(
                    user_id=owner_id,
                    store_id=second_store.id,
                    role_id=staff_role.id,
                ),
            ]
        )
        await session.flush()
        second_store_id = second_store.id

    token = await _login(security_harness)
    listed = await security_harness.client.get(
        "/api/v1/admin/organization/stores",
        headers=_bearer(token),
    )
    assert listed.status_code == 200
    assert [row["store"]["id"] for row in listed.json()] == [str(first_store_id)]

    denied = await security_harness.client.patch(
        f"/api/v1/admin/organization/stores/{second_store_id}/policy",
        headers=_bearer(token),
        json={
            "accepting_orders": True,
            "max_open_tickets": 50,
            "kds_heartbeat_seconds": 30,
            "printer_fallback_enabled": False,
            "expected_version": 1,
        },
    )
    assert denied.status_code == 403

    allowed = await security_harness.client.patch(
        f"/api/v1/admin/organization/stores/{first_store_id}/policy",
        headers=_bearer(token),
        json={
            "accepting_orders": True,
            "max_open_tickets": 50,
            "kds_heartbeat_seconds": 30,
            "printer_fallback_enabled": False,
            "expected_version": 1,
        },
    )
    assert allowed.status_code == 200
    assert allowed.json()["accepting_orders"] is True

    stale_policy_update = await security_harness.client.patch(
        f"/api/v1/admin/organization/stores/{first_store_id}/policy",
        headers=_bearer(token),
        json={
            "accepting_orders": False,
            "max_open_tickets": 10,
            "kds_heartbeat_seconds": 10,
            "printer_fallback_enabled": True,
            "expected_version": 1,
        },
    )
    assert stale_policy_update.status_code == 409
    assert stale_policy_update.json()["title"] == "stale_version"


@pytest.mark.anyio
async def test_organization_cross_tenant_store_access_is_denied(
    security_harness: SecurityHarness,
) -> None:
    async with security_harness.database.session_factory() as session, session.begin():
        other = await bootstrap_store(
            session,
            security_harness.settings,
            tenant_code="other-tenant",
            tenant_name="Other Tenant",
            legal_entity_code="other-entity",
            legal_entity_name="Other Retail B.V.",
            store_code="RTM-01",
            store_name="Rotterdam",
            owner_username="other-owner",
            owner_display_name="Other Owner",
            owner_password="another correct password",
        )

    token = await _login(security_harness)
    response = await security_harness.client.patch(
        f"/api/v1/admin/organization/stores/{other.store_id}/policy",
        headers=_bearer(token),
        json={
            "accepting_orders": True,
            "max_open_tickets": 50,
            "kds_heartbeat_seconds": 30,
            "printer_fallback_enabled": False,
            "expected_version": 1,
        },
    )
    assert response.status_code == 403

    users = await security_harness.client.get(
        "/api/v1/admin/users",
        headers=_bearer(token),
    )
    assert users.status_code == 200
    assert {user["username"] for user in users.json()} == {"owner"}


@pytest.mark.anyio
async def test_identity_bootstrap_duplicate_is_an_atomic_conflict() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        app_env="test",
        jwt_secret="phase-3-test-secret-that-is-at-least-thirty-two-bytes",
    )
    first = await _bootstrap(database, settings)
    assert first.kiosk_key not in repr(first)
    assert first.fulfillment_endpoint_key not in repr(first)

    with pytest.raises(ConflictError) as conflict:
        await _bootstrap(database, settings)
    assert conflict.value.code == "tenant_exists"

    async with database.session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Tenant)) == 1
        assert await session.scalar(select(func.count()).select_from(Store)) == 1
        assert await session.scalar(select(func.count()).select_from(KioskDevice)) == 1
        assert await session.scalar(select(func.count()).select_from(UserAccount)) == 1
        kiosk = await session.get(KioskDevice, UUID(first.kiosk_id))
        endpoint = await session.get(FulfillmentEndpoint, UUID(first.fulfillment_endpoint_id))
        assert kiosk is not None and kiosk.credential_hash != first.kiosk_key
        assert endpoint is not None and endpoint.credential_hash != first.fulfillment_endpoint_key
    await database.dispose()


@pytest.mark.anyio
async def test_organization_device_credentials_and_disablement(
    security_harness: SecurityHarness,
) -> None:
    kiosk_headers = {
        "X-Kiosk-ID": security_harness.bootstrap.kiosk_id,
        "X-Kiosk-Key": security_harness.bootstrap.kiosk_key,
    }
    endpoint_headers = {
        "X-Endpoint-ID": security_harness.bootstrap.fulfillment_endpoint_id,
        "X-Endpoint-Key": security_harness.bootstrap.fulfillment_endpoint_key,
    }
    kiosk = await security_harness.client.post(
        "/api/v1/kiosk/heartbeat",
        headers=kiosk_headers,
    )
    endpoint = await security_harness.client.post(
        "/api/v1/fulfillment/heartbeat",
        headers=endpoint_headers,
    )
    assert kiosk.status_code == 200
    assert endpoint.status_code == 200

    wrong_key = await security_harness.client.post(
        "/api/v1/kiosk/heartbeat",
        headers={
            "X-Kiosk-ID": security_harness.bootstrap.kiosk_id,
            "X-Kiosk-Key": "wrong-device-key-that-is-still-long-enough",
        },
    )
    assert wrong_key.status_code == 401
    assert "www-authenticate" not in wrong_key.headers

    missing_credentials = await security_harness.client.get("/api/v1/kiosk/store-status")
    assert missing_credentials.status_code == 401
    assert "www-authenticate" not in missing_credentials.headers

    async with security_harness.database.session_factory() as session, session.begin():
        kiosk_model = await session.get(KioskDevice, UUID(security_harness.bootstrap.kiosk_id))
        assert kiosk_model is not None
        kiosk_model.active = False
    disabled_kiosk = await security_harness.client.post(
        "/api/v1/kiosk/heartbeat",
        headers=kiosk_headers,
    )
    assert disabled_kiosk.status_code == 401

    async with security_harness.database.session_factory() as session, session.begin():
        tenant = await session.get(Tenant, UUID(security_harness.bootstrap.tenant_id))
        assert tenant is not None
        tenant.active = False
    disabled_tenant_endpoint = await security_harness.client.post(
        "/api/v1/fulfillment/heartbeat",
        headers=endpoint_headers,
    )
    assert disabled_tenant_endpoint.status_code == 401


@pytest.mark.anyio
async def test_store_creation_provisions_devices_and_rotates_credentials(
    security_harness: SecurityHarness,
) -> None:
    """A store created via the admin API is a usable, independent fulfilment unit.

    It must ship with its own kiosk, default kitchen station, KDS end-point and
    (mock) payment terminal, and rotate its secrets on an explicit reset.
    """
    harness = security_harness
    token = await _login(harness)

    created = await harness.client.post(
        "/api/v1/admin/organization/stores",
        headers=_bearer(token),
        json={
            "name": "Rotterdam Central",
            "city": "Rotterdam",
            "manager_display_name": "Rik Manager",
            "manager_username": "rik-admin",
            "manager_password": "rik-rotterdam-password-123",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    dev = body["device_credentials"]
    new_store_id = UUID(body["store"]["id"])
    assert dev["kiosk_id"] is not None
    assert dev["kiosk_key"] and len(dev["kiosk_key"]) >= 24
    assert dev["endpoint_id"] is not None
    assert dev["endpoint_key"] and len(dev["endpoint_key"]) >= 24
    assert dev["station_id"] is not None
    assert dev["terminal_id"] is not None

    async with harness.database.session_factory() as session, session.begin():
        store = await session.get(Store, new_store_id)
        assert store is not None
        kiosk = await session.scalar(
            select(KioskDevice).where(KioskDevice.store_id == store.id)
        )
        station = await session.scalar(
            select(KitchenStation).where(
                KitchenStation.store_id == store.id,
                KitchenStation.is_default,
            )
        )
        endpoint = await session.scalar(
            select(FulfillmentEndpoint)
            .join(KitchenStation, KitchenStation.id == FulfillmentEndpoint.station_id)
            .where(KitchenStation.store_id == store.id)
        )
        terminal = await session.scalar(
            select(PaymentTerminal)
            .join(KioskDevice, KioskDevice.id == PaymentTerminal.kiosk_id)
            .where(KioskDevice.store_id == store.id)
        )
        assert kiosk is not None
        assert station is not None
        assert endpoint is not None
        assert terminal is not None
        assert verify_device_credential(dev["kiosk_key"], kiosk.credential_hash)
        assert verify_device_credential(dev["endpoint_key"], endpoint.credential_hash)

    # A plain read never returns secrets.
    view = await harness.client.get(
        f"/api/v1/admin/organization/stores/{new_store_id}/device-credentials",
        headers=_bearer(token),
    )
    assert view.status_code == 200
    view_body = view.json()
    assert view_body["kiosk_id"] == dev["kiosk_id"]
    assert view_body["kiosk_key"] is None
    assert view_body["endpoint_key"] is None

    # Reset rotates both device secrets and returns them exactly once.
    reset = await harness.client.post(
        f"/api/v1/admin/organization/stores/{new_store_id}/device-credentials/reset",
        headers=_bearer(token),
    )
    assert reset.status_code == 200, reset.text
    rotated = reset.json()
    assert rotated["kiosk_key"] and rotated["kiosk_key"] != dev["kiosk_key"]
    assert rotated["endpoint_key"] and rotated["endpoint_key"] != dev["endpoint_key"]

    async with harness.database.session_factory() as session:
        kiosk = await session.scalar(
            select(KioskDevice).where(KioskDevice.store_id == new_store_id)
        )
        assert kiosk is not None
        assert verify_device_credential(rotated["kiosk_key"], kiosk.credential_hash)
        assert not verify_device_credential(dev["kiosk_key"], kiosk.credential_hash)

    manager_token = await _login(
        harness,
        username="rik-admin",
        password="rik-rotterdam-password-123",
    )
    own_policy = await harness.client.patch(
        f"/api/v1/admin/organization/stores/{new_store_id}/policy",
        headers=_bearer(manager_token),
        json={
            "accepting_orders": False,
            "max_open_tickets": 50,
            "kds_heartbeat_seconds": 30,
            "printer_fallback_enabled": False,
            "takeaway_fee_enabled": True,
            "takeaway_fee_minor": 50,
            "expected_version": 1,
        },
    )
    assert own_policy.status_code == 200, own_policy.text
    assert own_policy.json()["takeaway_fee_minor"] == 50

    foreign_policy = await harness.client.patch(
        f"/api/v1/admin/organization/stores/{harness.bootstrap.store_id}/policy",
        headers=_bearer(manager_token),
        json={
            "accepting_orders": False,
            "max_open_tickets": 50,
            "kds_heartbeat_seconds": 30,
            "printer_fallback_enabled": False,
            "takeaway_fee_enabled": True,
            "takeaway_fee_minor": 999,
            "expected_version": 1,
        },
    )
    assert foreign_policy.status_code == 403


@pytest.mark.anyio
async def test_kds_board_config_read_write_and_scope(
    security_harness: SecurityHarness,
) -> None:
    """Each store's KDS board is configurable and only admins/that store's manager may edit it."""
    harness = security_harness
    owner_token = await _login(harness)
    store_id = harness.bootstrap.store_id

    view = await harness.client.get(
        f"/api/v1/admin/organization/stores/{store_id}/kds-board",
        headers=_bearer(owner_token),
    )
    assert view.status_code == 200, view.text
    board = view.json()
    assert board["store_id"] == store_id
    assert board["station_id"]
    assert board["name"]  # default "Main Bar"
    assert board["display_title"] is None
    assert board["enabled"] is True
    assert board["version"] == 1

    update = await harness.client.patch(
        f"/api/v1/admin/organization/stores/{store_id}/kds-board",
        headers=_bearer(owner_token),
        json={
            "name": "Bar Board",
            "display_title": "Keuken",
            "enabled": True,
            "expected_version": 1,
        },
    )
    assert update.status_code == 200, update.text
    updated = update.json()
    assert updated["name"] == "Bar Board"
    assert updated["display_title"] == "Keuken"
    assert updated["enabled"] is True
    assert updated["version"] == 2

    stale = await harness.client.patch(
        f"/api/v1/admin/organization/stores/{store_id}/kds-board",
        headers=_bearer(owner_token),
        json={"name": "Stale", "expected_version": 1},
    )
    assert stale.status_code == 409

    # A staff user (no organization:write) is forbidden.
    await _create_staff_user(harness, owner_token)
    staff_token = await _login(
        harness, username="barista", password="barista-password-123"
    )
    denied = await harness.client.get(
        f"/api/v1/admin/organization/stores/{store_id}/kds-board",
        headers=_bearer(staff_token),
    )
    assert denied.status_code == 403


@pytest.mark.anyio
async def test_store_creation_creates_manager_account_and_connection_view(
    security_harness: SecurityHarness,
) -> None:
    """Creating a store provisions a store-manager account and returns a connection view."""
    harness = security_harness
    owner_token = await _login(harness)

    created = await harness.client.post(
        "/api/v1/admin/organization/stores",
        headers=_bearer(owner_token),
        json={
            "name": "Haarlem Shop",
            "city": "Haarlem",
            "manager_display_name": "Hanne Manager",
            "manager_username": "hanne-manager",
            "manager_password": "hanne-haarlem-password-123",
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    new_store_id = UUID(body["store"]["id"])
    account = body["manager_account"]
    assert account["username"] == "hanne-manager"
    assert account["display_name"] == "Hanne Manager"
    assert account["active"] is True
    assert body["tenant_code"] == "acme-nl"
    assert body["device_credentials"]["endpoint_id"]

    # The created manager can log in and sees only the new store.
    manager_token = await _login(
        harness,
        username="hanne-manager",
        password="hanne-haarlem-password-123",
    )
    listed = await harness.client.get(
        "/api/v1/admin/organization/stores",
        headers=_bearer(manager_token),
    )
    assert listed.status_code == 200
    assert [row["store"]["id"] for row in listed.json()] == [str(new_store_id)]

    # The connection view bundles tenant + devices + managers (no secret keys).
    view = await harness.client.get(
        f"/api/v1/admin/organization/stores/{new_store_id}/connection",
        headers=_bearer(owner_token),
    )
    assert view.status_code == 200, view.text
    connection = view.json()
    assert connection["tenant_code"] == "acme-nl"
    assert connection["endpoint_id"] == body["device_credentials"]["endpoint_id"]
    assert connection["kiosk_key"] is None
    assert connection["endpoint_key"] is None
    assert any(m["username"] == "hanne-manager" for m in connection["managers"])

    # The store manager can read their own store's connection view too.
    mgr_view = await harness.client.get(
        f"/api/v1/admin/organization/stores/{new_store_id}/connection",
        headers=_bearer(manager_token),
    )
    assert mgr_view.status_code == 200


@pytest.mark.anyio
async def test_refresh_token_mints_new_access_and_rotates(
    security_harness: SecurityHarness,
) -> None:
    harness = security_harness

    login_resp = await harness.client.post(
        "/api/v1/auth/token",
        json={
            "tenant_code": "acme-nl",
            "username": "owner",
            "password": "correct horse battery staple",
        },
    )
    assert login_resp.status_code == 200, login_resp.text
    first = login_resp.json()
    assert first["refresh_token"] and first["access_token"]
    refresh1 = first["refresh_token"]

    refresh_resp = await harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh1},
    )
    assert refresh_resp.status_code == 200, refresh_resp.text
    second = refresh_resp.json()
    assert second["access_token"]
    assert second["refresh_token"]
    assert second["access_token"] != first["access_token"]

    # The freshly minted access token is usable.
    me = await harness.client.get("/api/v1/auth/me", headers=_bearer(second["access_token"]))
    assert me.status_code == 200
    assert me.json()["user_id"]

    # An invalid / revoked-style refresh token is rejected.
    bad = await harness.client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "not-a-real-token"},
    )
    assert bad.status_code == 401
