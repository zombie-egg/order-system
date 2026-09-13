from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import uuid4

import jwt
from argon2 import PasswordHasher, extract_parameters
from argon2.exceptions import HashingError, InvalidHashError, VerificationError
from argon2.low_level import Type
from jwt import InvalidTokenError

# An explicit, OWASP-aligned Argon2id baseline keeps dependency upgrades from silently
# changing the password-hardening cost. Production hardware should benchmark this floor.
ARGON2_TIME_COST = 2
ARGON2_MEMORY_COST_KIB = 19 * 1024
ARGON2_PARALLELISM = 1
ARGON2_HASH_LENGTH = 32
ARGON2_SALT_LENGTH = 16
MAX_PASSWORD_BYTES = 1024

MIN_JWT_SECRET_BYTES = 32
MAX_ACCESS_TOKEN_LIFETIME = timedelta(hours=4)
MAX_ACCESS_TOKEN_BYTES = 16 * 1024
MAX_TOKEN_PERMISSIONS = 256
JWT_CLOCK_SKEW_SECONDS = 30

_PASSWORD_HASHER = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_COST_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LENGTH,
    salt_len=ARGON2_SALT_LENGTH,
    type=Type.ID,
)


class TokenValidationError(ValueError):
    """Raised when a bearer token is untrusted or no longer usable."""


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    subject: str
    tenant_id: str
    token_version: int
    permissions: tuple[str, ...]
    expires_at: datetime
    token_id: str


@dataclass(frozen=True, slots=True)
class RefreshTokenClaims:
    subject: str
    tenant_id: str
    token_version: int
    expires_at: datetime
    token_id: str


def _password_bytes(password: str) -> bytes:
    if not isinstance(password, str):
        raise ValueError("Password must be text")
    encoded = password.encode("utf-8")
    if not encoded or len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError(f"Password must contain between 1 and {MAX_PASSWORD_BYTES} UTF-8 bytes")
    return encoded


def hash_password(password: str) -> str:
    """Hash a staff password with Argon2id and a fresh random salt."""

    try:
        encoded_hash = _PASSWORD_HASHER.hash(_password_bytes(password))
    except HashingError as exc:
        raise ValueError("Password hashing failed") from exc
    if not encoded_hash.startswith("$argon2id$"):
        raise RuntimeError("The password hasher did not produce Argon2id")
    return cast(str, encoded_hash)


def _is_bounded_argon2id_hash(encoded_hash: str) -> bool:
    """Reject untrusted PHC parameters before they can cause resource exhaustion."""

    if len(encoded_hash) > 512:
        return False
    try:
        parameters = extract_parameters(encoded_hash)
    except (InvalidHashError, TypeError):
        return False
    return bool(
        parameters.type == Type.ID
        and parameters.version == 19
        and 1 <= parameters.time_cost <= 4
        and 8 * 1024 <= parameters.memory_cost <= 64 * 1024
        and 1 <= parameters.parallelism <= 4
        and 16 <= parameters.hash_len <= 64
        and 8 <= parameters.salt_len <= 32
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    if not isinstance(encoded_hash, str) or not _is_bounded_argon2id_hash(encoded_hash):
        return False
    try:
        return bool(_PASSWORD_HASHER.verify(encoded_hash, _password_bytes(password)))
    except (InvalidHashError, VerificationError, ValueError, UnicodeError):
        return False


def password_hash_needs_rehash(encoded_hash: str) -> bool:
    if not _is_bounded_argon2id_hash(encoded_hash):
        return True
    try:
        return bool(_PASSWORD_HASHER.check_needs_rehash(encoded_hash))
    except (InvalidHashError, TypeError):
        return True


def hash_device_credential(credential: str) -> str:
    """Hash a generated high-entropy device secret for equality lookup/verification.

    Device credentials are randomly generated 256-bit values, not human passwords, so a
    constant-time SHA-256 verifier is appropriate and avoids an avoidable Argon2 DoS surface.
    """

    if not isinstance(credential, str):
        raise ValueError("Device credential must be text")
    encoded = credential.encode("utf-8")
    if len(credential) < 24 or len(encoded) > MAX_PASSWORD_BYTES:
        raise ValueError("Device credential must contain between 24 and 1024 UTF-8 bytes")
    return hashlib.sha256(encoded).hexdigest()


def verify_device_credential(credential: str, expected_hash: str) -> bool:
    if not isinstance(credential, str) or not isinstance(expected_hash, str):
        return False
    if len(expected_hash) != 64:
        return False
    try:
        expected_digest = bytes.fromhex(expected_hash)
    except ValueError:
        return False
    if len(expected_digest) != hashlib.sha256().digest_size:
        return False
    try:
        encoded = credential.encode("utf-8")
    except UnicodeError:
        return False
    if len(encoded) > MAX_PASSWORD_BYTES:
        return False
    actual_digest = hashlib.sha256(encoded).digest()
    return hmac.compare_digest(actual_digest, expected_digest)


def _validate_jwt_secret(secret: str) -> None:
    if not isinstance(secret, str) or len(secret.encode("utf-8")) < MIN_JWT_SECRET_BYTES:
        raise ValueError(f"JWT secret must contain at least {MIN_JWT_SECRET_BYTES} UTF-8 bytes")


def _utc_timestamp(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Token time must be timezone-aware")
    return int(value.astimezone(UTC).timestamp())


def _is_strict_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def create_access_token(
    *,
    subject: str,
    tenant_id: str,
    token_version: int,
    permissions: set[str] | frozenset[str],
    secret: str,
    issuer: str,
    audience: str,
    lifetime: timedelta,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    _validate_jwt_secret(secret)
    if not subject or not tenant_id or not issuer or not audience:
        raise ValueError("Token identity, issuer, and audience must not be empty")
    if not _is_strict_integer(token_version) or token_version < 1:
        raise ValueError("Token version must be a positive integer")
    if lifetime <= timedelta(0) or lifetime > MAX_ACCESS_TOKEN_LIFETIME:
        raise ValueError("Access-token lifetime must be positive and no longer than four hours")
    if len(permissions) > MAX_TOKEN_PERMISSIONS or any(
        not isinstance(permission, str) or not permission or len(permission) > 100
        for permission in permissions
    ):
        raise ValueError("Token permissions are invalid")

    supplied_time = now or datetime.now(UTC)
    _utc_timestamp(supplied_time)
    issued_at = supplied_time.astimezone(UTC).replace(microsecond=0)
    issued_timestamp = _utc_timestamp(issued_at)
    expires_at = issued_at + lifetime
    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "token_version": token_version,
        "permissions": sorted(permissions),
        "iss": issuer,
        "aud": audience,
        "iat": issued_timestamp,
        "nbf": issued_timestamp,
        "exp": _utc_timestamp(expires_at),
        "jti": str(uuid4()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256", headers={"typ": "JWT"})
    if not isinstance(token, str):
        raise RuntimeError("JWT encoder returned an unexpected token type")
    return token, expires_at


def decode_access_token(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
    now: datetime | None = None,
) -> AccessTokenClaims:
    _validate_jwt_secret(secret)
    try:
        token_size = len(token.encode("utf-8")) if isinstance(token, str) else 0
    except UnicodeError as exc:
        raise TokenValidationError("Token format is invalid") from exc
    if (
        not isinstance(token, str)
        or not token
        or token.strip() != token
        or token_size > MAX_ACCESS_TOKEN_BYTES
    ):
        raise TokenValidationError("Token format is invalid")

    required_claims = (
        "sub",
        "tenant_id",
        "token_version",
        "permissions",
        "iss",
        "aud",
        "iat",
        "nbf",
        "exp",
        "jti",
    )
    try:
        header = jwt.get_unverified_header(token)
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise TokenValidationError("Token header is invalid")
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={
                "require": list(required_claims),
                "strict_aud": True,
                # Time is checked below so deterministic tests and clock injection use the
                # same validation path as production.
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
    except TokenValidationError:
        raise
    except (InvalidTokenError, TypeError, ValueError, UnicodeError) as exc:
        raise TokenValidationError("Token signature or claims are invalid") from exc

    subject = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    token_id = payload.get("jti")
    token_version = payload.get("token_version")
    permissions = payload.get("permissions")
    issued_at = payload.get("iat")
    not_before = payload.get("nbf")
    expires_at = payload.get("exp")

    if not isinstance(subject, str) or not subject:
        raise TokenValidationError("Token identity claims are invalid")
    if not isinstance(tenant_id, str) or not tenant_id:
        raise TokenValidationError("Token identity claims are invalid")
    if not isinstance(token_id, str) or not token_id:
        raise TokenValidationError("Token identity claims are invalid")
    if not _is_strict_integer(token_version):
        raise TokenValidationError("Token version is invalid")
    token_version = cast(int, token_version)
    if token_version < 1:
        raise TokenValidationError("Token version is invalid")
    if not all(_is_strict_integer(value) for value in (issued_at, not_before, expires_at)):
        raise TokenValidationError("Token time claims are invalid")
    if (
        not isinstance(permissions, list)
        or len(permissions) > MAX_TOKEN_PERMISSIONS
        or any(
            not isinstance(permission, str) or not permission or len(permission) > 100
            for permission in permissions
        )
        or len(permissions) != len(set(permissions))
    ):
        raise TokenValidationError("Token permissions are invalid")

    assert isinstance(issued_at, int)
    assert isinstance(not_before, int)
    assert isinstance(expires_at, int)
    if expires_at <= issued_at or not_before < issued_at or not_before > expires_at:
        raise TokenValidationError("Token validity window is invalid")
    if expires_at - issued_at > int(MAX_ACCESS_TOKEN_LIFETIME.total_seconds()):
        raise TokenValidationError("Token lifetime is too long")

    current_timestamp = _utc_timestamp(now or datetime.now(UTC))
    if issued_at > current_timestamp + JWT_CLOCK_SKEW_SECONDS:
        raise TokenValidationError("Token issue time is in the future")
    if not_before > current_timestamp + JWT_CLOCK_SKEW_SECONDS:
        raise TokenValidationError("Token is not active")
    if expires_at <= current_timestamp:
        raise TokenValidationError("Token has expired")

    return AccessTokenClaims(
        subject=subject,
        tenant_id=tenant_id,
        token_version=token_version,
        permissions=tuple(permissions),
        expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
        token_id=token_id,
    )


MAX_REFRESH_TOKEN_LIFETIME = timedelta(days=365)
MAX_REFRESH_TOKEN_BYTES = 16 * 1024


def create_refresh_token(
    *,
    subject: str,
    tenant_id: str,
    token_version: int,
    secret: str,
    issuer: str,
    audience: str,
    lifetime: timedelta,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Issue a long-lived, stateless refresh JWT (no database storage required)."""
    _validate_jwt_secret(secret)
    if not subject or not tenant_id or not issuer or not audience:
        raise ValueError("Token identity, issuer, and audience must not be empty")
    if not _is_strict_integer(token_version) or token_version < 1:
        raise ValueError("Token version must be a positive integer")
    if lifetime <= timedelta(0) or lifetime > MAX_REFRESH_TOKEN_LIFETIME:
        raise ValueError("Refresh-token lifetime must be positive and no longer than one year")
    supplied_time = now or datetime.now(UTC)
    issued_at = supplied_time.astimezone(UTC).replace(microsecond=0)
    issued_timestamp = _utc_timestamp(issued_at)
    expires_at = issued_at + lifetime
    payload: dict[str, Any] = {
        "sub": subject,
        "tenant_id": tenant_id,
        "token_version": token_version,
        "typ": "refresh",
        "iss": issuer,
        "aud": audience,
        "iat": issued_timestamp,
        "nbf": issued_timestamp,
        "exp": _utc_timestamp(expires_at),
        "jti": str(uuid4()),
    }
    token = jwt.encode(payload, secret, algorithm="HS256", headers={"typ": "JWT"})
    if not isinstance(token, str):
        raise RuntimeError("JWT encoder returned an unexpected token type")
    return token, expires_at


def decode_refresh_token(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
    now: datetime | None = None,
) -> RefreshTokenClaims:
    _validate_jwt_secret(secret)
    try:
        token_size = len(token.encode("utf-8")) if isinstance(token, str) else 0
    except UnicodeError as exc:
        raise TokenValidationError("Token format is invalid") from exc
    if (
        not isinstance(token, str)
        or not token
        or token.strip() != token
        or token_size > MAX_REFRESH_TOKEN_BYTES
    ):
        raise TokenValidationError("Token format is invalid")

    required_claims = (
        "sub",
        "tenant_id",
        "token_version",
        "typ",
        "iss",
        "aud",
        "iat",
        "nbf",
        "exp",
        "jti",
    )
    try:
        header = jwt.get_unverified_header(token)
        if header != {"alg": "HS256", "typ": "JWT"}:
            raise TokenValidationError("Token header is invalid")
        payload = jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            issuer=issuer,
            audience=audience,
            options={
                "require": list(required_claims),
                "strict_aud": True,
                "verify_exp": False,
                "verify_iat": False,
                "verify_nbf": False,
            },
        )
    except TokenValidationError:
        raise
    except (InvalidTokenError, TypeError, ValueError, UnicodeError) as exc:
        raise TokenValidationError("Token signature or claims are invalid") from exc

    if payload.get("typ") != "refresh":
        raise TokenValidationError("Token is not a refresh token")
    subject = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    token_id = payload.get("jti")
    token_version = payload.get("token_version")
    issued_at = payload.get("iat")
    not_before = payload.get("nbf")
    expires_at = payload.get("exp")
    if not all(isinstance(value, str) and value for value in (subject, tenant_id, token_id)):
        raise TokenValidationError("Token identity claims are invalid")
    if not _is_strict_integer(token_version):
        raise TokenValidationError("Token version is invalid")
    token_version = cast(int, token_version)
    if not all(_is_strict_integer(value) for value in (issued_at, not_before, expires_at)):
        raise TokenValidationError("Token time claims are invalid")
    assert isinstance(expires_at, int)
    current_timestamp = _utc_timestamp(now or datetime.now(UTC))
    if expires_at <= current_timestamp:
        raise TokenValidationError("Token has expired")
    return RefreshTokenClaims(
        subject=cast(str, subject),
        tenant_id=cast(str, tenant_id),
        token_version=token_version,
        expires_at=datetime.fromtimestamp(expires_at, tz=UTC),
        token_id=cast(str, token_id),
    )
