from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, IdempotencyStatus
from app.core.errors import ConflictError
from app.core.principals import Principal
from app.core.request_context import correlation_id_context
from app.core.sensitive_data import contains_sensitive_card_data
from app.modules.audit.models import AuditLog, IdempotencyRecord, OutboxEvent
from app.persistence.base import utc_now


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        default=str,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


canonical_json_hash = canonical_hash


async def list_audit_logs(
    session: AsyncSession,
    principal: Principal,
    *,
    limit: int,
) -> list[AuditLog]:
    query = select(AuditLog).where(AuditLog.tenant_id == principal.tenant_id)
    if "audit:tenant_read" not in principal.permissions:
        if not principal.store_ids:
            return []
        query = query.where(AuditLog.store_id.in_(principal.store_ids))
    return list(
        (await session.scalars(query.order_by(AuditLog.occurred_at.desc()).limit(limit))).all()
    )


def hash_idempotency_key(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ConflictError("idempotency_key_required", "Idempotency-Key is required")
    if len(normalized) > 200:
        raise ConflictError("idempotency_key_too_long", "Idempotency-Key is too long")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IdempotencyClaim:
    record: IdempotencyRecord
    replayed: bool


async def claim_idempotency(
    session: AsyncSession,
    *,
    namespace: str,
    actor_scope: str,
    idempotency_key: str,
    request_payload: Any,
    expires_at: datetime | None = None,
) -> IdempotencyClaim:
    record, created = await acquire_idempotency_record(
        session,
        namespace=namespace,
        actor_scope=actor_scope,
        idempotency_key=idempotency_key,
        request_payload=request_payload,
        expires_at=expires_at,
    )
    if not created and (record.status != IdempotencyStatus.COMPLETED or record.resource_id is None):
        raise ConflictError(
            "idempotency_request_in_progress",
            "The original request is still being processed",
        )
    return IdempotencyClaim(record=record, replayed=not created)


async def acquire_idempotency_record(
    session: AsyncSession,
    *,
    namespace: str,
    actor_scope: str,
    idempotency_key: str,
    request_payload: Any,
    expires_at: datetime | None = None,
) -> tuple[IdempotencyRecord, bool]:
    key_hash = hash_idempotency_key(idempotency_key)
    request_hash = canonical_hash(request_payload)
    record_id = uuid4()
    values = {
        "id": record_id,
        "namespace": namespace,
        "actor_scope": actor_scope,
        "idempotency_key": key_hash,
        "request_hash": request_hash,
        "status": IdempotencyStatus.PROCESSING,
        "created_at": utc_now(),
        "expires_at": expires_at,
    }
    dialect_name = session.get_bind().dialect.name
    if dialect_name == "postgresql":
        postgres_statement = (
            postgresql_insert(IdempotencyRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["namespace", "actor_scope", "idempotency_key"])
        )
        await session.execute(postgres_statement)
    elif dialect_name == "sqlite":
        sqlite_statement = (
            sqlite_insert(IdempotencyRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["namespace", "actor_scope", "idempotency_key"])
        )
        await session.execute(sqlite_statement)
    else:
        raise RuntimeError(f"Unsupported database dialect: {dialect_name}")
    created = await session.get(IdempotencyRecord, record_id) is not None
    record = await session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.namespace == namespace,
            IdempotencyRecord.actor_scope == actor_scope,
            IdempotencyRecord.idempotency_key == key_hash,
        )
    )
    if record is None:
        raise RuntimeError("The idempotency record could not be acquired")
    if record.request_hash != request_hash:
        raise ConflictError(
            "idempotency_key_reused",
            "The idempotency key was already used with a different request",
        )
    return record, created


def complete_idempotency(
    record: IdempotencyRecord,
    *,
    resource_type: str,
    resource_id: UUID,
    response_status: int,
    response_json: dict[str, Any],
) -> None:
    record.status = IdempotencyStatus.COMPLETED
    record.resource_type = resource_type
    record.resource_id = resource_id
    record.response_status = response_status
    record.response_json = response_json


complete_idempotency_record = complete_idempotency


def add_audit_log(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    store_id: UUID | None,
    actor_type: ActorType,
    action: str,
    target_type: str,
    target_id: UUID,
    actor_user_id: UUID | None = None,
    actor_device_id: UUID | None = None,
    correlation_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> AuditLog:
    if contains_sensitive_card_data({"before": before, "after": after, "metadata": metadata}):
        raise ValueError("Audit data must not contain cardholder authentication data")
    event = AuditLog(
        tenant_id=tenant_id,
        store_id=store_id,
        actor_type=actor_type,
        actor_user_id=actor_user_id,
        actor_device_id=actor_device_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        correlation_id=correlation_id or correlation_id_context.get(),
        before_redacted=before,
        after_redacted=after,
        metadata_redacted=metadata or {},
        occurred_at=occurred_at or utc_now(),
    )
    session.add(event)
    return event


def add_outbox_event(
    session: AsyncSession,
    *,
    store_id: UUID | None = None,
    aggregate_type: str,
    aggregate_id: UUID,
    event_type: str,
    deduplication_key: str,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> OutboxEvent:
    if contains_sensitive_card_data(payload):
        raise ValueError("Outbox payloads must not contain cardholder authentication data")
    now = occurred_at or utc_now()
    event = OutboxEvent(
        store_id=store_id,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        event_type=event_type,
        schema_version=1,
        deduplication_key=deduplication_key,
        payload=payload,
        occurred_at=now,
        available_at=now,
    )
    session.add(event)
    return event
