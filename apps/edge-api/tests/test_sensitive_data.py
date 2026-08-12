from __future__ import annotations

import json
import logging
import sys

from app.core.logging import JsonFormatter
from app.core.sensitive_data import contains_sensitive_card_data, redact_sensitive_card_data
from app.modules.payments.sanitization import (
    sanitize_masked_account,
    sanitize_provider_identifier,
)


def test_sensitive_data_detection_uses_card_semantics_without_uuid_false_positives() -> None:
    assert contains_sensitive_card_data("4111111111111111")
    assert contains_sensitive_card_data("4111 1111 1111 1111")
    assert contains_sensitive_card_data("CVV=123")
    assert contains_sensitive_card_data({"card_number": "not-even-digits"})

    assert not contains_sensitive_card_data("receipt 00000000-0000-0000-0000-123456789012")
    assert not contains_sensitive_card_data("reference 1234567890123456")
    assert redact_sensitive_card_data("card 4111-1111-1111-1111") == "card [REDACTED]"


def test_structured_error_logs_do_not_serialize_exception_messages_or_tracebacks() -> None:
    try:
        raise RuntimeError("CVV=654")
    except RuntimeError:
        record = logging.LogRecord(
            name="app.main",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="unhandled_request_error",
            args=(),
            exc_info=sys.exc_info(),
        )
    record.correlation_id = "security-test"
    record.request_method = "POST"
    record.request_path = "/api/v1/orders"
    record.exception_type = "RuntimeError"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "unhandled_request_error"
    assert payload["exception_type"] == "RuntimeError"
    assert "exception" not in payload
    assert "654" not in json.dumps(payload)


def test_provider_identifiers_do_not_hash_raw_card_authentication_data() -> None:
    unsafe_identifier = "event-card-4111111111111111-CVV=123"
    first = sanitize_provider_identifier(
        unsafe_identifier,
        fallback_scope="authorization:test-attempt",
    )
    second = sanitize_provider_identifier(
        unsafe_identifier,
        fallback_scope="authorization:test-attempt",
    )
    same_redacted_shape = sanitize_provider_identifier(
        "event-card-5555555555554444-CVV=999",
        fallback_scope="authorization:test-attempt",
    )

    assert first == second
    assert first == same_redacted_shape
    assert first.startswith("redacted-")
    assert "4111111111111111" not in first
    assert "123" not in first


def test_masked_account_accepts_common_commercial_mask_characters() -> None:
    assert sanitize_masked_account("************1111") == "************1111"
    assert sanitize_masked_account("•••• 1111") == "•••• 1111"
    assert sanitize_masked_account("4111111111111111") is None
