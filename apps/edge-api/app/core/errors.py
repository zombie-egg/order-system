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
    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__("unauthorized", message, status_code=401)
