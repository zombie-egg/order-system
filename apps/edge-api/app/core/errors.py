from __future__ import annotations

from typing import Any


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class NotFoundError(DomainError):
    def __init__(self, entity: str, entity_id: str) -> None:
        super().__init__(
            "not_found",
            f"{entity} was not found",
            status_code=404,
            details={"entity": entity, "id": entity_id},
        )


class ConflictError(DomainError):
    def __init__(self, code: str, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code, message, status_code=409, details=details)


class ForbiddenError(DomainError):
    def __init__(self, message: str = "Insufficient permission") -> None:
        super().__init__("forbidden", message, status_code=403)


class UnauthorizedError(DomainError):
    def __init__(
        self,
        message: str = "Authentication required",
        *,
        authenticate_header: str | None = "Bearer",
    ) -> None:
        super().__init__("unauthorized", message, status_code=401)
        self.authenticate_header = authenticate_header


class TooManyRequestsError(DomainError):
    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__("too_many_requests", message, status_code=429)
        self.response_headers = {"Retry-After": str(max(1, retry_after_seconds))}
