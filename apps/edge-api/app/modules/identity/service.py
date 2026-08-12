from __future__ import annotations

import asyncio
import hmac
from datetime import datetime, timedelta
from hashlib import sha256
from math import ceil
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.enums import ActorType
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
)
from app.core.principals import Principal
from app.core.security import (
    create_access_token,
    hash_password,
    password_hash_needs_rehash,
    verify_password,
)
from app.modules.audit.service import add_audit_log
from app.modules.identity.models import (
    LoginThrottle,
    Permission,
    Role,
    RolePermission,
    UserAccount,
    UserStoreRole,
)
from app.modules.identity.schemas import CreateUserRequest, LoginRequest
from app.modules.organization.models import LegalEntity, Store, Tenant
from app.persistence.base import utc_now
from app.persistence.database import Database

_DUMMY_PASSWORD_HASH = hash_password("dummy-password-used-only-to-equalize-failed-logins")
_NONEXISTENT_TENANT_ID = UUID(int=0)


class PasswordVerifier(Protocol):
    async def verify(self, password: str, password_hash: str) -> bool: ...

    async def hash(self, password: str) -> str: ...


class PasswordVerificationLimiter:
    def __init__(self, capacity: int) -> None:
        self._semaphore = asyncio.Semaphore(capacity)

    async def verify(self, password: str, password_hash: str) -> bool:
        async with self._semaphore:
            return await asyncio.to_thread(verify_password, password, password_hash)

    async def hash(self, password: str) -> str:
        async with self._semaphore:
            return await asyncio.to_thread(hash_password, password)

    async def run_dummy_verification(self, password: str) -> None:
        await self.verify(password, _DUMMY_PASSWORD_HASH)


def normalize_identifier(value: str) -> str:
    return value.strip().casefold()


def _login_principal_key(settings: Settings, tenant_code: str, username: str) -> str:
    normalized = f"{normalize_identifier(tenant_code)}\0{normalize_identifier(username)}"
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        normalized.encode("utf-8"),
        sha256,
    ).hexdigest()


def _retry_after_seconds(locked_until: datetime, now: datetime) -> int:
    return max(1, ceil((locked_until - now).total_seconds()))


def _reset_throttle(throttle: LoginThrottle, now: datetime) -> None:
    throttle.failed_attempts = 0
    throttle.window_started_at = now
    throttle.last_failed_at = now
    throttle.locked_until = None


async def _create_throttle_if_missing(
    session: AsyncSession,
    settings: Settings,
    *,
    principal_key: str,
    now: datetime,
) -> LoginThrottle:
    retention_seconds = (
        max(settings.login_failure_window_seconds, settings.login_lockout_seconds) * 4
    )
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(
            delete(LoginThrottle).where(
                LoginThrottle.principal_key != principal_key,
                LoginThrottle.last_failed_at < now - timedelta(seconds=retention_seconds),
            )
        )
    values = {
        "principal_key": principal_key,
        "failed_attempts": 0,
        "window_started_at": now,
        "last_failed_at": now,
        "locked_until": None,
    }
    dialect_name = session.get_bind().dialect.name
    statement: Any
    if dialect_name == "sqlite":
        statement = (
            sqlite_insert(LoginThrottle)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[LoginThrottle.principal_key])
        )
    elif dialect_name == "postgresql":
        statement = (
            postgresql_insert(LoginThrottle)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[LoginThrottle.principal_key])
        )
    else:
        raise RuntimeError(f"Unsupported login throttle database dialect: {dialect_name}")
    await session.execute(statement)
    throttle = await session.get(LoginThrottle, principal_key, with_for_update=True)
    if throttle is None:
        raise RuntimeError("Login throttle row could not be created")
    return throttle


async def authenticate(
    database: Database,
    settings: Settings,
    request: LoginRequest,
    password_limiter: PasswordVerifier,
) -> tuple[str, datetime]:
    principal_key = _login_principal_key(settings, request.tenant_code, request.username)
    result: tuple[str, datetime] | None = None
    invalid_credentials = False
    retry_after_seconds: int | None = None

    async with database.session_factory() as session, session.begin():
        now = utc_now()
        throttle = await _create_throttle_if_missing(
            session,
            settings,
            principal_key=principal_key,
            now=now,
        )
        if throttle.locked_until is not None:
            if throttle.locked_until > now:
                retry_after_seconds = _retry_after_seconds(throttle.locked_until, now)
            else:
                _reset_throttle(throttle, now)
        if retry_after_seconds is None and now >= throttle.window_started_at + timedelta(
            seconds=settings.login_failure_window_seconds
        ):
            _reset_throttle(throttle, now)

        if retry_after_seconds is None:
            tenant = await session.scalar(
                select(Tenant).where(
                    Tenant.code == normalize_identifier(request.tenant_code),
                    Tenant.active,
                )
            )
            user = await session.scalar(
                select(UserAccount).where(
                    UserAccount.tenant_id
                    == (tenant.id if tenant is not None else _NONEXISTENT_TENANT_ID),
                    UserAccount.username_normalized == normalize_identifier(request.username),
                )
            )
            password_valid = await password_limiter.verify(
                request.password,
                user.password_hash if user is not None else _DUMMY_PASSWORD_HASH,
            )
            invalid_credentials = (
                tenant is None or user is None or not user.active or not password_valid
            )
            if invalid_credentials:
                throttle.failed_attempts += 1
                throttle.last_failed_at = now
                if throttle.failed_attempts >= settings.login_max_failures:
                    throttle.locked_until = now + timedelta(seconds=settings.login_lockout_seconds)
                    retry_after_seconds = settings.login_lockout_seconds
            else:
                assert tenant is not None
                assert user is not None
                await session.delete(throttle)
                rows = (
                    await session.execute(
                        select(UserStoreRole.store_id, Permission.code)
                        .join(Role, Role.id == UserStoreRole.role_id)
                        .join(Store, Store.id == UserStoreRole.store_id)
                        .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
                        .join(Tenant, Tenant.id == LegalEntity.tenant_id)
                        .join(RolePermission, RolePermission.role_id == UserStoreRole.role_id)
                        .join(Permission, Permission.id == RolePermission.permission_id)
                        .where(
                            UserStoreRole.user_id == user.id,
                            Role.tenant_id == user.tenant_id,
                            LegalEntity.tenant_id == user.tenant_id,
                            Tenant.active,
                            LegalEntity.active,
                            Store.active,
                        )
                    )
                ).all()
                permissions = {permission for _, permission in rows}
                if password_hash_needs_rehash(user.password_hash):
                    user.password_hash = await password_limiter.hash(request.password)
                user.last_login_at = now
                result = create_access_token(
                    subject=str(user.id),
                    tenant_id=str(user.tenant_id),
                    token_version=user.token_version,
                    permissions=permissions,
                    secret=settings.jwt_secret,
                    issuer=settings.jwt_issuer,
                    audience=settings.jwt_audience,
                    lifetime=timedelta(minutes=settings.access_token_minutes),
                )

    if retry_after_seconds is not None:
        if isinstance(password_limiter, PasswordVerificationLimiter):
            await password_limiter.run_dummy_verification(request.password)
        raise TooManyRequestsError(
            "Too many authentication attempts. Try again later",
            retry_after_seconds=retry_after_seconds,
        )
    if invalid_credentials or result is None:
        raise UnauthorizedError(
            "Username or password is incorrect",
            authenticate_header=None,
        )
    return result


async def create_user(
    session: AsyncSession,
    principal: Principal,
    request: CreateUserRequest,
) -> UserAccount:
    principal.require_store(request.store_id)
    store_exists = await session.scalar(
        select(Store.id)
        .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
        .where(
            Store.id == request.store_id,
            Store.active,
            LegalEntity.active,
            LegalEntity.tenant_id == principal.tenant_id,
        )
    )
    if store_exists is None:
        raise NotFoundError("store", str(request.store_id))
    requested_role_codes = {
        normalize_identifier(role_code) for role_code in request.role_codes if role_code.strip()
    }
    if not requested_role_codes:
        raise ConflictError("role_not_found", "One or more role codes are invalid")
    roles = list(
        (
            await session.scalars(
                select(Role)
                .where(
                    Role.tenant_id == principal.tenant_id,
                    Role.code.in_(requested_role_codes),
                )
                .with_for_update()
            )
        ).all()
    )
    roles_by_code = {role.code: role for role in roles}
    if set(roles_by_code) != requested_role_codes:
        raise ConflictError("role_not_found", "One or more role codes are invalid")
    requested_permissions = set(
        (
            await session.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id.in_(role.id for role in roles))
            )
        ).all()
    )
    if not requested_permissions.issubset(principal.permissions_for_store(request.store_id)):
        raise ForbiddenError("A user cannot grant permissions they do not hold for this store")
    user = UserAccount(
        tenant_id=principal.tenant_id,
        username=request.username.strip(),
        username_normalized=normalize_identifier(request.username),
        display_name=request.display_name.strip(),
        password_hash=hash_password(request.password),
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
            session.add_all(
                UserStoreRole(user_id=user.id, store_id=request.store_id, role_id=role.id)
                for role in roles
            )
            await session.flush()
    except IntegrityError as exc:
        raise ConflictError("username_exists", "The username already exists") from exc
    add_audit_log(
        session,
        tenant_id=principal.tenant_id,
        store_id=request.store_id,
        actor_type=ActorType.USER,
        actor_user_id=principal.user_id,
        action="identity.user.created",
        target_type="user_account",
        target_id=user.id,
        after={
            "active": user.active,
            "role_codes": sorted(requested_role_codes),
            "version": user.version,
        },
    )
    return user


async def list_users(session: AsyncSession, principal: Principal) -> list[UserAccount]:
    if not principal.store_ids:
        return []
    return list(
        (
            await session.scalars(
                select(UserAccount)
                .join(UserStoreRole, UserStoreRole.user_id == UserAccount.id)
                .where(
                    UserAccount.tenant_id == principal.tenant_id,
                    UserStoreRole.store_id.in_(principal.store_ids),
                )
                .distinct()
                .order_by(UserAccount.username_normalized)
            )
        ).all()
    )


async def update_user_status(
    session: AsyncSession,
    principal: Principal,
    user_id: UUID,
    *,
    active: bool,
    expected_version: int,
) -> UserAccount:
    user = await session.scalar(
        select(UserAccount)
        .where(
            UserAccount.id == user_id,
            UserAccount.tenant_id == principal.tenant_id,
        )
        .with_for_update()
    )
    if user is None:
        raise NotFoundError("user_account", str(user_id))
    target_store_ids = frozenset(
        (
            await session.scalars(
                select(UserStoreRole.store_id)
                .join(Role, Role.id == UserStoreRole.role_id)
                .join(Store, Store.id == UserStoreRole.store_id)
                .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
                .where(
                    UserStoreRole.user_id == user.id,
                    Role.tenant_id == principal.tenant_id,
                    LegalEntity.tenant_id == principal.tenant_id,
                )
                .distinct()
            )
        ).all()
    )
    if not target_store_ids or not target_store_ids.issubset(principal.store_ids):
        raise ForbiddenError("The user has assignments outside the caller's authorized store scope")
    if user.version != expected_version:
        raise ConflictError("stale_version", "The user account was modified by another request")
    if user.id == principal.user_id and not active:
        raise ConflictError("self_disable_forbidden", "A user cannot disable their own account")
    before = {
        "active": user.active,
        "token_version": user.token_version,
        "version": user.version,
    }
    updated_user = await session.scalar(
        update(UserAccount)
        .where(
            UserAccount.id == user.id,
            UserAccount.tenant_id == principal.tenant_id,
            UserAccount.version == expected_version,
        )
        .values(
            active=active,
            token_version=UserAccount.token_version + 1,
            version=UserAccount.version + 1,
        )
        .returning(UserAccount)
        .execution_options(populate_existing=True)
    )
    if updated_user is None:
        raise ConflictError("stale_version", "The user account was modified by another request")
    for store_id in sorted(target_store_ids, key=str):
        add_audit_log(
            session,
            tenant_id=principal.tenant_id,
            store_id=store_id,
            actor_type=ActorType.USER,
            actor_user_id=principal.user_id,
            action="identity.user.status_changed",
            target_type="user_account",
            target_id=updated_user.id,
            before=before,
            after={
                "active": updated_user.active,
                "token_version": updated_user.token_version,
                "version": updated_user.version,
            },
        )
    return updated_user
