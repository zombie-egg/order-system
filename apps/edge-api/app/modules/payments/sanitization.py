from __future__ import annotations

import hashlib

from app.core.sensitive_data import contains_sensitive_card_data, redact_sensitive_card_data


def sanitize_masked_account(value: str | None) -> str | None:
    """Keep display-safe last-four data and discard possible cardholder data."""
    if value is None:
        return None
    normalized = value.strip()
    digits = "".join(character for character in normalized if character.isdigit())
    has_mask = any(character in normalized for character in ("*", "•", "X", "x"))
    if (
        not normalized
        or len(normalized) > 40
        or len(digits) > 4
        or not has_mask
        or contains_sensitive_card_data(normalized)
    ):
        return None
    return normalized


def sanitize_provider_text(value: str | None, *, maximum_length: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return redact_sensitive_card_data(normalized)[:maximum_length]


def sanitize_provider_identifier(
    value: str,
    *,
    maximum_length: int = 160,
    fallback_scope: str | None = None,
) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("A provider event identifier cannot be blank")
    contains_sensitive_data = contains_sensitive_card_data(normalized)
    if len(normalized) <= maximum_length and not contains_sensitive_data:
        return normalized
    # Never persist a deterministic hash derived directly from PAN/CVV/PIN data. A
    # redacted value plus a business-resource scope remains replay-stable without
    # retaining a verifier for low-entropy authentication data such as a CVV.
    safe_basis = redact_sensitive_card_data(normalized) if contains_sensitive_data else normalized
    digest_source = f"{fallback_scope or 'provider-event'}:{safe_basis}"
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return f"redacted-{digest}"
