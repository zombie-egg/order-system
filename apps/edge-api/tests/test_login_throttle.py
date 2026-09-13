from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select

import app.persistence.models  # noqa: F401
from app.core.config import Settings
from app.core.errors import TooManyRequestsError, UnauthorizedError
from app.modules.identity import service as identity_service
from app.modules.identity.models import LoginThrottle, UserAccount
from app.modules.identity.schemas import LoginRequest
from app.modules.organization.models import Tenant
from app.persistence.base import Base, utc_now
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class DeterministicPasswordLimiter:
    async def verify(self, password: str, password_hash: str) -> bool:
        return password == "correct" and password_hash == "stored-hash"

    async def hash(self, password: str) -> str:
        return f"rehash:{password}"


@pytest.mark.anyio
async def test_durable_login_throttle_locks_and_recovers_without_raw_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="login-throttle-test-secret-that-is-long-enough",
        login_max_failures=3,
        login_failure_window_seconds=60,
        login_lockout_seconds=30,
    )
    tenant_id = uuid4()
    async with database.session_factory() as session, session.begin():
        session.add(Tenant(id=tenant_id, code="acme-nl", name="ACME Netherlands"))
        await session.flush()
        session.add(
            UserAccount(
                tenant_id=tenant_id,
                username="owner",
                username_normalized="owner",
                display_name="Owner",
                password_hash="stored-hash",
            )
        )

    monkeypatch.setattr(identity_service, "password_hash_needs_rehash", lambda _: False)
    monkeypatch.setattr(
        identity_service,
        "create_access_token",
        lambda **_: ("test-token", utc_now() + timedelta(minutes=5)),
    )
    limiter = DeterministicPasswordLimiter()
    wrong_request = LoginRequest(
        tenant_code="acme-nl",
        username="owner",
        password="wrong",
    )
    for _ in range(2):
        with pytest.raises(UnauthorizedError):
            await identity_service.authenticate(database, settings, wrong_request, limiter)
    with pytest.raises(TooManyRequestsError) as locked:
        await identity_service.authenticate(database, settings, wrong_request, limiter)
    assert locked.value.response_headers == {"Retry-After": "30"}

    correct_request = LoginRequest(
        tenant_code="acme-nl",
        username="owner",
        password="correct",
    )
    with pytest.raises(TooManyRequestsError):
        await identity_service.authenticate(database, settings, correct_request, limiter)

    async with database.session_factory() as session, session.begin():
        throttle = await session.scalar(select(LoginThrottle))
        assert throttle is not None
        assert throttle.failed_attempts == 3
        assert len(throttle.principal_key) == 64
        assert "acme" not in throttle.principal_key
        assert "owner" not in throttle.principal_key
        throttle.locked_until = utc_now() - timedelta(seconds=1)

    token, _, _ = await identity_service.authenticate(database, settings, correct_request, limiter)
    assert token == "test-token"
    async with database.session_factory() as session:
        assert await session.scalar(select(func.count(LoginThrottle.principal_key))) == 0
    await database.dispose()
