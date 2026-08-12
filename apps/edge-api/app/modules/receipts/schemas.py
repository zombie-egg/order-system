from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.enums import ReceiptType


class ReceiptResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    order_id: UUID
    refund_id: UUID | None
    receipt_type: ReceiptType
    receipt_number: str
    locale: str
    currency: str
    document: dict[str, Any]
    content_hash: str
    generated_at: datetime
    printed_at: datetime | None


class KioskReceiptResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    receipt_type: ReceiptType
    receipt_number: str
    locale: str
    currency: str
    document: dict[str, Any]
    generated_at: datetime


def to_kiosk_receipt_response(receipt: ReceiptResponse) -> KioskReceiptResponse:
    payload = receipt.model_dump()
    payload["document"] = _to_kiosk_document(receipt.document)
    return KioskReceiptResponse.model_validate(payload)


_KIOSK_DOCUMENT_PRIVATE_KEYS = frozenset(
    {
        "content_hash",
        "failure_code",
        "printed_at",
        "provider",
        "psp_reference",
        "refund_id",
        "version",
    }
)


def _to_kiosk_document(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _to_kiosk_document(item)
            for key, item in value.items()
            if key not in _KIOSK_DOCUMENT_PRIVATE_KEYS
        }
    if isinstance(value, list):
        return [_to_kiosk_document(item) for item in value]
    return deepcopy(value)
