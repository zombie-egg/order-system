from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select

import app.persistence.models  # noqa: F401
from app.bootstrap import bootstrap_store
from app.core.config import Settings
from app.main import create_app
from app.modules.organization.models import KitchenStation
from app.persistence.base import Base
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _assert_success(response: Response, expected_status: int = 200) -> dict[str, Any]:
    assert response.status_code == expected_status, response.text
    payload = response.json()
    assert isinstance(payload, dict)
    return payload


@pytest.mark.anyio
async def test_complete_http_sale_fulfillment_review_refund_and_reporting_workflow() -> None:
    database = Database("sqlite+aiosqlite:///:memory:")
    async with database.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    settings = Settings(
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="phase-3-http-workflow-secret-at-least-thirty-two-bytes",
    )
    async with database.session_factory() as session, session.begin():
        bootstrap = await bootstrap_store(
            session,
            settings,
            tenant_code="http-test-nl",
            tenant_name="HTTP Test Netherlands",
            legal_entity_code="http-test-retail-nl",
            legal_entity_name="HTTP Test Retail Nederland B.V.",
            store_code="AMS-HTTP-01",
            store_name="Amsterdam HTTP Test Store",
            owner_username="owner",
            owner_display_name="Store Owner",
            owner_password="correct horse battery staple",
        )

    application = create_app(settings=settings, database=database)
    transport = ASGITransport(app=application)
    now = datetime.now(UTC).replace(microsecond=0)
    kiosk_headers = {
        "X-Kiosk-ID": bootstrap.kiosk_id,
        "X-Kiosk-Key": bootstrap.kiosk_key,
    }
    endpoint_headers = {
        "X-Endpoint-ID": bootstrap.fulfillment_endpoint_id,
        "X-Endpoint-Key": bootstrap.fulfillment_endpoint_key,
    }
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            login = _assert_success(
                await client.post(
                    "/api/v1/auth/token",
                    json={
                        "tenant_code": "http-test-nl",
                        "username": "owner",
                        "password": "correct horse battery staple",
                    },
                )
            )
            staff_headers = {"Authorization": f"Bearer {login['access_token']}"}

            _assert_success(
                await client.patch(
                    f"/api/v1/admin/organization/stores/{bootstrap.store_id}/policy",
                    headers=staff_headers,
                    json={
                        "accepting_orders": True,
                        "max_open_tickets": 50,
                        "kds_heartbeat_seconds": 30,
                        "printer_fallback_enabled": False,
                        "takeaway_fee_enabled": True,
                        "takeaway_fee_minor": 35,
                        "expected_version": 1,
                    },
                )
            )
            option_group = _assert_success(
                await client.post(
                    "/api/v1/admin/catalog/option-groups",
                    headers=staff_headers,
                    json={
                        "store_id": bootstrap.store_id,
                        "code": "formaat",
                        "translations": {"nl-NL": "Formaat", "en": "Size"},
                        "values": [
                            {
                                "code": "groot",
                                "translations": {"nl-NL": "Groot", "en": "Large"},
                            }
                        ],
                    },
                ),
                201,
            )
            option_groups_response = await client.get(
                f"/api/v1/admin/catalog/stores/{bootstrap.store_id}/option-groups",
                headers=staff_headers,
            )
            assert option_groups_response.status_code == 200
            option_groups = option_groups_response.json()
            assert isinstance(option_groups, list)
            option_value_id = option_groups[0]["values"][0]["id"]
            category = _assert_success(
                await client.post(
                    "/api/v1/admin/catalog/categories",
                    headers=staff_headers,
                    json={
                        "store_id": bootstrap.store_id,
                        "code": "hot-drinks",
                        "translations": {"nl-NL": "Warme dranken", "en": "Hot drinks"},
                        "sort_order": 10,
                    },
                ),
                201,
            )
            product = _assert_success(
                await client.post(
                    "/api/v1/admin/catalog/products",
                    headers=staff_headers,
                    json={
                        "store_id": bootstrap.store_id,
                        "category_id": category["id"],
                        "sku": "COFFEE-HTTP-01",
                        "tax_category_code": "BEVERAGE",
                        "translations": {
                            "nl-NL": {"name": "Koffie", "description": "Vers bereid"},
                            "en": {"name": "Coffee", "description": "Freshly prepared"},
                        },
                        "preparation_data": {"workflow": "manual-bar"},
                        "allergen_data": {"contains": []},
                        "option_rules": [
                            {
                                "option_group_id": option_group["id"],
                                "minimum_selections": 1,
                                "maximum_selections": 1,
                                "default_option_value_id": option_value_id,
                            }
                        ],
                    },
                ),
                201,
            )
            _assert_success(
                await client.post(
                    "/api/v1/admin/pricing/tax-policies",
                    headers=staff_headers,
                    json={
                        "store_id": bootstrap.store_id,
                        "version": 1,
                        "valid_from": (now - timedelta(days=1)).isoformat(),
                        "rates": [{"tax_category_code": "BEVERAGE", "rate_ppm": 90_000}],
                    },
                ),
                201,
            )
            _assert_success(
                await client.post(
                    "/api/v1/admin/catalog/price-books",
                    headers=staff_headers,
                    json={
                        "store_id": bootstrap.store_id,
                        "code": "default-http",
                        "version": 1,
                        "currency": "EUR",
                        "prices_include_tax": True,
                        "valid_from": (now - timedelta(hours=1)).isoformat(),
                        "items": [
                            {
                                "product_id": product["id"],
                                "price_minor": 350,
                                "option_prices": [
                                    {
                                        "option_value_id": option_value_id,
                                        "price_delta_minor": 75,
                                    }
                                ],
                            }
                        ],
                    },
                ),
                201,
            )

            catalog_response = await client.get(
                "/api/v1/kiosk/catalog",
                headers=kiosk_headers,
                params={"locale": "nl-NL"},
            )
            assert catalog_response.status_code == 200, catalog_response.text
            assert catalog_response.json()["categories"][0]["products"][0]["name"] == "Koffie"
            tampered_quote = await client.post(
                "/api/v1/kiosk/quotes",
                headers=kiosk_headers,
                json={
                    "locale": "nl-NL",
                    "fulfillment_type": "TAKEAWAY",
                    "packaging_fee_minor": 1,
                    "items": [
                        {
                            "product_id": product["id"],
                            "quantity": 1,
                            "option_value_ids": [option_value_id],
                            "price_minor": 1,
                        }
                    ],
                },
            )
            assert tampered_quote.status_code == 422

            heartbeat_response = await client.post(
                "/api/v1/fulfillment/heartbeat",
                headers=endpoint_headers,
            )
            assert heartbeat_response.status_code == 200, heartbeat_response.text

            async def create_kiosk_order(
                key_suffix: str, fulfillment_type: str, expected_total: int
            ) -> dict[str, Any]:
                quote = _assert_success(
                    await client.post(
                        "/api/v1/kiosk/quotes",
                        headers=kiosk_headers,
                        json={
                            "locale": "nl-NL",
                            "fulfillment_type": fulfillment_type,
                            "items": [
                                {
                                    "product_id": product["id"],
                                    "quantity": 1,
                                    "option_value_ids": [option_value_id],
                                }
                            ],
                        },
                    ),
                    201,
                )
                assert quote["total_minor"] == expected_total
                assert quote["items"][0]["option_total_minor"] == 75
                return _assert_success(
                    await client.post(
                        "/api/v1/kiosk/orders",
                        headers={
                            **kiosk_headers,
                            "Idempotency-Key": f"http-order-{key_suffix}",
                        },
                        json={"quote_id": quote["id"], "payment_method": "CARD"},
                    ),
                    201,
                )

            sale_order = await create_kiosk_order("sale", "TAKEAWAY", 460)
            sale_attempt_id = sale_order["payment_attempts"][0]["id"]
            paid_order = _assert_success(
                await client.post(
                    f"/api/v1/kiosk/payment-attempts/{sale_attempt_id}/execute",
                    headers=kiosk_headers,
                )
            )
            assert paid_order["status"] == "CONFIRMED"
            assert paid_order["payment_status"] == "PAID"
            assert paid_order["packaging_fee_minor"] == 35
            assert paid_order["fulfillment_type"] == "TAKEAWAY"

            queue_headers = {**endpoint_headers, **staff_headers}
            queue_response = await client.get(
                "/api/v1/fulfillment/tickets",
                headers=queue_headers,
            )
            assert queue_response.status_code == 200, queue_response.text
            queue = queue_response.json()
            assert len(queue) == 1
            ticket = queue[0]
            assert ticket["fulfillment_type"] == "TAKEAWAY"
            assert ticket["items"][0]["options"] == ["Formaat: Groot"]
            for next_status in ("ACKNOWLEDGED", "PREPARING", "READY", "COLLECTED"):
                ticket = _assert_success(
                    await client.post(
                        f"/api/v1/fulfillment/tickets/{ticket['id']}/transition",
                        headers=queue_headers,
                        json={
                            "to_status": next_status,
                            "expected_version": ticket["version"],
                        },
                    )
                )
                assert ticket["status"] == next_status

            sale_receipts_response = await client.get(
                f"/api/v1/kiosk/orders/{sale_order['id']}/receipts",
                headers=kiosk_headers,
            )
            assert sale_receipts_response.status_code == 200, sale_receipts_response.text
            assert [receipt["receipt_type"] for receipt in sale_receipts_response.json()] == [
                "SALE"
            ]
            sale_document = sale_receipts_response.json()[0]["document"]
            assert sale_document["order"]["fulfillment_type"] == "TAKEAWAY"
            assert sale_document["amounts"]["packaging_fee_minor"] == 35
            assert sale_document["items"][0]["options"][0]["name"] == "Groot"

            review_order = await create_kiosk_order("review", "DINE_IN", 425)
            async with database.session_factory() as session, session.begin():
                station = await session.scalar(
                    select(KitchenStation).where(
                        KitchenStation.store_id == UUID(bootstrap.store_id)
                    )
                )
                assert station is not None
                station.is_default = False

            review_attempt_id = review_order["payment_attempts"][0]["id"]
            held_order = _assert_success(
                await client.post(
                    f"/api/v1/kiosk/payment-attempts/{review_attempt_id}/execute",
                    headers=kiosk_headers,
                )
            )
            assert held_order["payment_status"] == "PAID"

            reviews_response = await client.get(
                "/api/v1/admin/reviews",
                headers=staff_headers,
            )
            assert reviews_response.status_code == 200, reviews_response.text
            review = next(
                item for item in reviews_response.json() if item["order_id"] == review_order["id"]
            )
            review = _assert_success(
                await client.post(
                    f"/api/v1/admin/reviews/{review['id']}/assign",
                    headers=staff_headers,
                    json={"expected_version": review["version"], "assignee_user_id": None},
                )
            )
            review = _assert_success(
                await client.post(
                    f"/api/v1/admin/reviews/{review['id']}/resolve",
                    headers={**staff_headers, "Idempotency-Key": "http-review-full-refund"},
                    json={
                        "expected_version": review["version"],
                        "resolution": "FULL_REFUND",
                        "notes": "Customer approved refund after manual review",
                        "payload": {},
                    },
                )
            )
            assert review["status"] == "ACTION_PENDING"

            refunds_response = await client.get(
                "/api/v1/admin/payments/refunds",
                headers=staff_headers,
            )
            assert refunds_response.status_code == 200, refunds_response.text
            refund = next(
                item for item in refunds_response.json() if item["order_id"] == review_order["id"]
            )
            refund = _assert_success(
                await client.post(
                    f"/api/v1/admin/payments/refunds/{refund['id']}/execute",
                    headers=staff_headers,
                )
            )
            assert refund["status"] == "SUCCEEDED"

            review_receipts_response = await client.get(
                f"/api/v1/kiosk/orders/{review_order['id']}/receipts",
                headers=kiosk_headers,
            )
            assert review_receipts_response.status_code == 200, review_receipts_response.text
            assert {receipt["receipt_type"] for receipt in review_receipts_response.json()} == {
                "SALE",
                "REFUND",
            }

            extra_value = _assert_success(
                await client.post(
                    f"/api/v1/admin/catalog/stores/{bootstrap.store_id}/option-groups/{option_group['id']}/values",
                    headers=staff_headers,
                    json={
                        "code": "extra-groot",
                        "translations": {"nl-NL": "Extra groot"},
                        "sort_order": 20,
                    },
                ),
                201,
            )
            _assert_success(
                await client.patch(
                    f"/api/v1/admin/catalog/stores/{bootstrap.store_id}/option-groups/{option_group['id']}",
                    headers=staff_headers,
                    json={"translations": {"nl-NL": "Bekerformaat"}, "sort_order": 5},
                )
            )
            _assert_success(
                await client.patch(
                    f"/api/v1/admin/catalog/stores/{bootstrap.store_id}/option-groups/{option_group['id']}/values/{extra_value['id']}",
                    headers=staff_headers,
                    json={"active": False, "sort_order": 30},
                )
            )

            report_response = await client.get(
                "/api/v1/admin/reports/sales",
                headers=staff_headers,
                params={
                    "store_id": bootstrap.store_id,
                    "start_at": (now - timedelta(days=1)).isoformat(),
                    "end_at": (now + timedelta(days=1)).isoformat(),
                },
            )
            report = _assert_success(report_response)
            assert report["order_count"] == 2
            assert report["paid_minor"] == 885
            assert report["refunded_minor"] == 425
            assert report["net_collected_minor"] == 460
            _assert_success(
                await client.patch(
                    f"/api/v1/admin/catalog/stores/{bootstrap.store_id}/option-groups/{option_group['id']}/values/{option_value_id}",
                    headers=staff_headers,
                    json={"active": False},
                )
            )
            inactive_quote = await client.post(
                "/api/v1/kiosk/quotes",
                headers=kiosk_headers,
                json={
                    "locale": "nl-NL",
                    "fulfillment_type": "DINE_IN",
                    "items": [
                        {
                            "product_id": product["id"],
                            "quantity": 1,
                            "option_value_ids": [option_value_id],
                        }
                    ],
                },
            )
            assert inactive_quote.status_code == 409
    finally:
        await database.dispose()
