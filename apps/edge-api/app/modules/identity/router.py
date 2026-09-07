from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.dependencies import (
    CurrentPrincipal,
    Principal,
    SessionDependency,
    SettingsDependency,
    get_database,
    require_permission,
)
from app.core.enums import PermissionCode
from app.modules.identity.schemas import (
    AccessTokenResponse,
    CreateUserRequest,
    LoginRequest,
    PrincipalResponse,
    RefreshRequest,
    UpdateUserStatusRequest,
    UserResponse,
)
from app.modules.identity.service import (
    PasswordVerificationLimiter,
    authenticate,
    create_user,
    list_users,
    refresh_access_token,
    update_user_status,
)
from app.persistence.database import Database

router = APIRouter(tags=["identity"])
admin_router = APIRouter(prefix="/admin/users", tags=["admin-users"])
DatabaseDependency = Annotated[Database, Depends(get_database)]


def get_password_verification_limiter(request: Request) -> PasswordVerificationLimiter:
    return cast(
        PasswordVerificationLimiter,
        request.app.state.password_verification_limiter,
    )


PasswordLimiterDependency = Annotated[
    PasswordVerificationLimiter,
    Depends(get_password_verification_limiter),
]


def _disable_sensitive_response_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


@router.post("/auth/token", response_model=AccessTokenResponse, operation_id="create_access_token")
async def login(
    request: LoginRequest,
    response: Response,
    database: DatabaseDependency,
    settings: SettingsDependency,
    password_limiter: PasswordLimiterDependency,
) -> AccessTokenResponse:
    _disable_sensitive_response_caching(response)
    token, expires_at, refresh_token = await authenticate(
        database, settings, request, password_limiter
    )
    return AccessTokenResponse(
        access_token=token,
        expires_at=expires_at,
        refresh_token=refresh_token,
    )


@router.post(
    "/auth/refresh",
    response_model=AccessTokenResponse,
    operation_id="refresh_access_token",
)
async def refresh(
    request: RefreshRequest,
    response: Response,
    database: DatabaseDependency,
    settings: SettingsDependency,
) -> AccessTokenResponse:
    _disable_sensitive_response_caching(response)
    token, expires_at, refresh_token = await refresh_access_token(
        database, settings, request.refresh_token
    )
    return AccessTokenResponse(
        access_token=token,
        expires_at=expires_at,
        refresh_token=refresh_token,
    )


@router.get("/auth/me", response_model=PrincipalResponse, operation_id="get_current_principal")
async def me(response: Response, principal: CurrentPrincipal) -> PrincipalResponse:
    _disable_sensitive_response_caching(response)
    return PrincipalResponse(
        user_id=principal.user_id,
        tenant_id=principal.tenant_id,
        permissions=sorted(principal.permissions),
        store_ids=sorted(principal.store_ids, key=str),
    )


IdentityReadPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.IDENTITY_READ.value))
]
IdentityWritePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.IDENTITY_WRITE.value))
]


@admin_router.get("", response_model=list[UserResponse], operation_id="list_users")
async def get_users(
    response: Response,
    session: SessionDependency,
    principal: IdentityReadPrincipal,
) -> list[UserResponse]:
    _disable_sensitive_response_caching(response)
    return [UserResponse.model_validate(user) for user in await list_users(session, principal)]


@admin_router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_user",
)
async def post_user(
    request: CreateUserRequest,
    response: Response,
    session: SessionDependency,
    principal: IdentityWritePrincipal,
) -> UserResponse:
    _disable_sensitive_response_caching(response)
    return UserResponse.model_validate(await create_user(session, principal, request))


@admin_router.patch(
    "/{user_id}/status", response_model=UserResponse, operation_id="update_user_status"
)
async def patch_user_status(
    user_id: UUID,
    request: UpdateUserStatusRequest,
    response: Response,
    session: SessionDependency,
    principal: IdentityWritePrincipal,
) -> UserResponse:
    _disable_sensitive_response_caching(response)
    user = await update_user_status(
        session,
        principal,
        user_id,
        active=request.active,
        expected_version=request.expected_version,
    )
    return UserResponse.model_validate(user)
