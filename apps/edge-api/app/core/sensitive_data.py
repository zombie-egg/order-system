from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

CONTIGUOUS_PAN_CANDIDATE = re.compile(r"(?<!\d)\d{13,19}(?!\d)")
GROUPED_PAN_CANDIDATE = re.compile(r"(?<![\d-])(?:\d{4}[ -]){3,4}\d{3,4}(?![\d-])")
SECRET_LABEL_VALUE = re.compile(r"(?i)\b(cvv|cvc|cid|pin)\b\s*[:=]\s*[^\s,;]+")
SENSITIVE_FIELD_NAMES = {
    "cardnumber",
    "card_number",
    "cvc",
    "cvv",
    "cid",
    "magneticstripe",
    "magnetic_stripe",
    "pan",
    "pin",
    "track1",
    "track2",
}


def _passes_luhn(candidate: str) -> bool:
    digits = [int(character) for character in candidate if character.isdigit()]
    if not 12 <= len(digits) <= 19:
        return False
    checksum = 0
    parity = len(digits) % 2
    for index, digit in enumerate(digits):
        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9
        checksum += digit
    return checksum % 10 == 0


def _redact_pan_match(match: re.Match[str]) -> str:
    candidate = match.group(0)
    return "[REDACTED]" if _passes_luhn(candidate) else candidate


def redact_sensitive_card_data(value: str) -> str:
    redacted = GROUPED_PAN_CANDIDATE.sub(_redact_pan_match, value)
    redacted = CONTIGUOUS_PAN_CANDIDATE.sub(_redact_pan_match, redacted)
    return SECRET_LABEL_VALUE.sub(
        lambda match: f"{match.group(1).upper()}=[REDACTED]",
        redacted,
    )


def contains_sensitive_card_data(value: Any) -> bool:
    if isinstance(value, str):
        return redact_sensitive_card_data(value) != value
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).strip().casefold().replace("-", "_").replace(" ", "_")
            if normalized_key in SENSITIVE_FIELD_NAMES or contains_sensitive_card_data(item):
                return True
        return False
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_sensitive_card_data(item) for item in value)
    return False
