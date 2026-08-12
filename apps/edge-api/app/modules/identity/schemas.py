from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.api_models import StrictRequestModel


def _validate_password_bytes(value: str) -> str:
    if len(value.encode("utf-8")) > 1024:
        raise ValueError("Password must contain at most 1024 UTF-8 bytes")
    return value


class LoginRequest(StrictRequestModel):
    tenant_code: str = Field(min_length=1, max_length=50)
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=1024)

    @field_validator("tenant_code", "username")
    @classmethod
    def identifiers_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Identifier must not be blank")
        return value

    @field_validator("password")
    @classmethod
    def password_must_fit_hashing_limit(cls, value: str) -> str:
        return _validate_password_bytes(value)


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime


class PrincipalResponse(BaseModel):
    user_id: UUID
    tenant_id: UUID
    permissions: list[str]
    store_ids: list[UUID]


class CreateUserRequest(StrictRequestModel):
    store_id: UUID
    username: str = Field(min_length=1, max_length=120)
    display_name: str = Field(min_length=1, max_length=160)
    password: str = Field(min_length=12, max_length=1024)
    role_codes: list[str] = Field(min_length=1, max_length=10)

    @field_validator("username", "display_name")
    @classmethod
    def user_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Value must not be blank")
        return value

    @field_validator("username")
    @classmethod
    def normalized_username_must_fit(cls, value: str) -> str:
        if len(value.strip().casefold()) > 120:
            raise ValueError("Normalized username must contain at most 120 characters")
        return value

    @field_validator("password")
    @classmethod
    def password_must_fit_hashing_limit(cls, value: str) -> str:
        return _validate_password_bytes(value)

    @field_validator("role_codes")
    @classmethod
    def role_codes_must_be_bounded(cls, value: list[str]) -> list[str]:
        if any(not role_code.strip() or len(role_code) > 50 for role_code in value):
            raise ValueError("Role codes must be non-blank and at most 50 characters")
        return value


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    username: str
    display_name: str
    active: bool
    token_version: int
    version: int
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UpdateUserStatusRequest(StrictRequestModel):
    active: bool
    expected_version: int = Field(ge=1)
