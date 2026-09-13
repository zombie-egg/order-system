from datetime import UTC, date, datetime
from uuid import UUID

from app.core.enums import (
    OrderStatus,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    ReceiptType,
)
from app.modules.ordering.schemas import (
    OrderItemResponse,
    OrderOptionResponse,
    OrderResponse,
    PaymentAttemptResponse,
    to_kiosk_order_response,
)
from app.modules.receipts.schemas import ReceiptResponse, to_kiosk_receipt_response

ORDER_ID = UUID("00000000-0000-0000-0000-000000000001")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000002")
STORE_ID = UUID("00000000-0000-0000-0000-000000000003")
KIOSK_ID = UUID("00000000-0000-0000-0000-000000000004")
QUOTE_ID = UUID("00000000-0000-0000-0000-000000000005")
ITEM_ID = UUID("00000000-0000-0000-0000-000000000006")
PRODUCT_ID = UUID("00000000-0000-0000-0000-000000000007")
OPTION_ID = UUID("00000000-0000-0000-0000-000000000008")
RECEIPT_ID = UUID("00000000-0000-0000-0000-000000000009")
REFUND_ID = UUID("00000000-0000-0000-0000-000000000010")
NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _staff_order_response() -> OrderResponse:
    return OrderResponse(
        id=ORDER_ID,
        store_id=STORE_ID,
        kiosk_id=KIOSK_ID,
        quote_id=QUOTE_ID,
        business_date=date(2026, 8, 12),
        order_number="20260812-000001",
        display_number="A001",
        status=OrderStatus.CONFIRMED,
        payment_status=PaymentStatus.PAID,
        currency="EUR",
        locale="nl-NL",
        prices_include_tax=True,
        subtotal_minor=350,
        discount_minor=0,
        net_minor=321,
        tax_minor=29,
        total_minor=350,
        paid_minor=350,
        refunded_minor=0,
        confirmed_at=NOW,
        closed_at=None,
        version=7,
        items=[
            OrderItemResponse(
                id=ITEM_ID,
                line_number=1,
                product_id=PRODUCT_ID,
                sku="INTERNAL-SKU-001",
                name="Iced Latte",
                quantity=1,
                unit_price_minor=300,
                option_total_minor=50,
                discount_minor=0,
                net_minor=321,
                tax_minor=29,
                line_total_minor=350,
                allergen_snapshot={"allergens": ["milk"]},
                options=[
                    OrderOptionResponse(
                        option_value_id=OPTION_ID,
                        group_name="Size",
                        name="Large",
                        price_delta_minor=50,
                    )
                ],
            )
        ],
        payment_attempts=[
            PaymentAttemptResponse(
                id=ATTEMPT_ID,
                attempt_number=1,
                provider=PaymentProvider.ADYEN,
                payment_method=PaymentMethod.CONTACTLESS,
                status=PaymentStatus.PAID,
                amount_minor=350,
                currency="EUR",
                psp_reference="PSP-SENSITIVE-REFERENCE",
                failure_code="PSP-INTERNAL-CODE",
                requested_at=NOW,
                completed_at=NOW,
                version=4,
            )
        ],
    )


def test_kiosk_order_contract_keeps_customer_flow_fields_only() -> None:
    response = to_kiosk_order_response(_staff_order_response())
    payload = response.model_dump(mode="json")

    assert set(payload) == {
        "id",
        "display_number",
        "status",
        "payment_status",
        "currency",
        "locale",
        "prices_include_tax",
        "fulfillment_type",
        "packaging_fee_minor",
        "subtotal_minor",
        "discount_minor",
        "net_minor",
        "tax_minor",
        "total_minor",
        "paid_minor",
        "refunded_minor",
        "items",
        "payment_attempts",
    }
    assert payload["id"] == str(ORDER_ID)
    assert payload["display_number"] == "A001"
    assert payload["total_minor"] == 350

    item = payload["items"][0]
    assert set(item) == {
        "line_number",
        "name",
        "quantity",
        "unit_price_minor",
        "option_total_minor",
        "discount_minor",
        "net_minor",
        "tax_minor",
        "line_total_minor",
        "allergen_snapshot",
        "options",
    }
    assert set(item["options"][0]) == {"group_name", "name", "price_delta_minor"}

    attempt = payload["payment_attempts"][0]
    assert set(attempt) == {
        "id",
        "payment_method",
        "status",
        "amount_minor",
        "currency",
    }
    assert attempt["id"] == str(ATTEMPT_ID)


def test_staff_order_contract_remains_complete() -> None:
    payload = _staff_order_response().model_dump(mode="json")

    assert payload["store_id"] == str(STORE_ID)
    assert payload["kiosk_id"] == str(KIOSK_ID)
    assert payload["quote_id"] == str(QUOTE_ID)
    assert payload["version"] == 7
    assert payload["items"][0]["product_id"] == str(PRODUCT_ID)
    assert payload["payment_attempts"][0]["provider"] == "ADYEN"
    assert payload["payment_attempts"][0]["psp_reference"] == "PSP-SENSITIVE-REFERENCE"
    assert payload["payment_attempts"][0]["failure_code"] == "PSP-INTERNAL-CODE"
    assert payload["payment_attempts"][0]["version"] == 4


def test_kiosk_receipt_contract_keeps_customer_document_only() -> None:
    staff_response = ReceiptResponse(
        id=RECEIPT_ID,
        order_id=ORDER_ID,
        refund_id=REFUND_ID,
        receipt_type=ReceiptType.REFUND,
        receipt_number="R-20260812-000001",
        locale="nl-NL",
        currency="EUR",
        document={
            "schema_version": 1,
            "title": "Refund receipt",
            "order_id": str(ORDER_ID),
            "refund_id": str(REFUND_ID),
            "total_minor": 350,
            "payment": {
                "provider": "ADYEN",
                "psp_reference": "PSP-SENSITIVE-REFERENCE",
                "failure_code": "PSP-INTERNAL-CODE",
                "version": 4,
            },
        },
        content_hash="internal-integrity-hash",
        generated_at=NOW,
        printed_at=NOW,
    )

    response = to_kiosk_receipt_response(staff_response)
    payload = response.model_dump(mode="json")

    assert set(payload) == {
        "receipt_type",
        "receipt_number",
        "locale",
        "currency",
        "document",
        "generated_at",
    }
    assert payload["receipt_type"] == "REFUND"
    assert payload["receipt_number"] == "R-20260812-000001"
    assert payload["document"] == {
        "schema_version": 1,
        "title": "Refund receipt",
        "order_id": str(ORDER_ID),
        "total_minor": 350,
        "payment": {},
    }

    staff_payload = staff_response.model_dump(mode="json")
    assert staff_payload["id"] == str(RECEIPT_ID)
    assert staff_payload["order_id"] == str(ORDER_ID)
    assert staff_payload["refund_id"] == str(REFUND_ID)
    assert staff_payload["content_hash"] == "internal-integrity-hash"
    assert staff_payload["printed_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert staff_payload["document"]["refund_id"] == str(REFUND_ID)
    assert staff_payload["document"]["payment"]["provider"] == "ADYEN"
    assert staff_payload["document"]["payment"]["psp_reference"] == "PSP-SENSITIVE-REFERENCE"
