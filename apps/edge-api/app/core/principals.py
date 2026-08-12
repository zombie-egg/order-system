from __future__ import annotations

from dataclasses import dataclass, field, replace
from uuid import UUID

from app.core.errors import ForbiddenError


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    permissions: frozenset[str]
    store_ids: frozenset[UUID]
    # A tuple keeps the frozen principal deeply immutable and deterministic. The empty
    # default remains useful for trusted service-level tests and explicit DI overrides.
    permission_store_ids: tuple[tuple[str, frozenset[UUID]], ...] = field(
        default_factory=tuple,
        repr=False,
    )

    def require_store(self, store_id: UUID) -> None:
        if store_id not in self.store_ids:
            raise ForbiddenError("The user is not authorized for this store")

    def permissions_for_store(self, store_id: UUID) -> frozenset[str]:
        """Return only permissions granted to this principal at ``store_id``.

        Production principals always carry the permission-to-store mapping loaded from
        the database.  The fallback preserves the deliberately lightweight principals
        used by trusted service-level tests and dependency overrides.
        """

        if store_id not in self.store_ids:
            return frozenset()
        if not self.permission_store_ids:
            return self.permissions
        return frozenset(
            permission
            for permission, scoped_store_ids in self.permission_store_ids
            if store_id in scoped_store_ids
        )

    def scope_to_permission(self, permission: str) -> Principal:
        if permission not in self.permissions:
            raise ForbiddenError(f"Missing permission: {permission}")
        if not self.permission_store_ids:
            return self
        authorized_store_ids = next(
            (
                store_ids
                for mapped_permission, store_ids in self.permission_store_ids
                if mapped_permission == permission
            ),
            frozenset(),
        )
        return replace(self, store_ids=self.store_ids & authorized_store_ids)


@dataclass(frozen=True, slots=True)
class KioskPrincipal:
    kiosk_id: UUID
    store_id: UUID


@dataclass(frozen=True, slots=True)
class FulfillmentEndpointPrincipal:
    endpoint_id: UUID
    station_id: UUID
