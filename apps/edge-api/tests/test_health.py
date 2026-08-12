import re
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient, Response

from app.core.config import Settings
from app.main import create_app
from app.modules.manual_review.schemas import ResolveReviewRequest
from app.persistence.database import Database


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


TEST_SETTINGS = Settings(
    app_env="test",
    database_url="sqlite+aiosqlite:///:memory:",
)


async def get(path: str) -> Response:
    application = create_app(settings=TEST_SETTINGS)
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)
    finally:
        await application.state.database.dispose()


@pytest.mark.anyio
async def test_live_health_endpoint() -> None:
    response = await get("/api/v1/health/live")
    settings = TEST_SETTINGS

    assert response.status_code == 200
    assert response.json() == {
        "status": "alive",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@pytest.mark.anyio
async def test_ready_health_endpoint() -> None:
    response = await get("/api/v1/health/ready")
    settings = TEST_SETTINGS

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": settings.app_name,
        "version": settings.app_version,
    }


@pytest.mark.anyio
async def test_version_endpoint() -> None:
    response = await get("/api/v1/version")
    settings = TEST_SETTINGS

    assert response.status_code == 200
    assert response.json() == {
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.app_env,
        "country": settings.default_country,
    }


@pytest.mark.anyio
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/version",
    ],
)
async def test_technical_responses_are_not_cached(path: str) -> None:
    response = await get(path)

    assert response.headers["cache-control"] == "no-store"


@pytest.mark.anyio
async def test_openapi_exposes_unique_explicit_phase_3_operation_ids() -> None:
    response = await get("/openapi.json")
    document = response.json()

    paths = set(document["paths"])
    assert {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/version",
        "/api/v1/auth/token",
        "/api/v1/kiosk/catalog",
        "/api/v1/kiosk/quotes",
        "/api/v1/kiosk/orders",
        "/api/v1/admin/reviews",
        "/api/v1/admin/reports/sales",
    }.issubset(paths)
    operation_ids = [
        operation["operationId"]
        for path in document["paths"].values()
        for operation in path.values()
    ]
    assert len(operation_ids) == len(set(operation_ids))
    assert {"get_liveness", "get_readiness", "get_version"}.issubset(operation_ids)

    security_schemes = document["components"]["securitySchemes"]
    assert security_schemes["StaffBearerAuth"]["type"] == "http"
    assert security_schemes["StaffBearerAuth"]["scheme"] == "bearer"
    assert security_schemes["KioskDeviceId"] == {
        "type": "apiKey",
        "description": "Provisioned kiosk device identifier.",
        "in": "header",
        "name": "X-Kiosk-ID",
    }
    assert security_schemes["KioskDeviceKey"] == {
        "type": "apiKey",
        "description": "Provisioned high-entropy kiosk device secret.",
        "in": "header",
        "name": "X-Kiosk-Key",
    }
    assert document["paths"]["/api/v1/kiosk/catalog"]["get"]["security"] == [
        {"KioskDeviceId": [], "KioskDeviceKey": []}
    ]
    assert document["paths"]["/api/v1/fulfillment/heartbeat"]["post"]["security"] == [
        {"FulfillmentEndpointId": [], "FulfillmentEndpointKey": []}
    ]
    assert document["paths"]["/api/v1/fulfillment/tickets"]["get"]["security"] == [
        {
            "FulfillmentEndpointId": [],
            "FulfillmentEndpointKey": [],
            "StaffBearerAuth": [],
        }
    ]
    assert document["paths"]["/api/v1/admin/organization/stores"]["get"]["security"] == [
        {"StaffBearerAuth": []}
    ]


@pytest.mark.anyio
async def test_openapi_cache_includes_routes_registered_after_app_creation() -> None:
    application = create_app(settings=TEST_SETTINGS)

    @application.get("/api/v1/_test/late-openapi-route", operation_id="late_openapi_route")
    async def late_route() -> dict[str, bool]:
        return {"ok": True}

    try:
        document = application.openapi()
        assert "/api/v1/_test/late-openapi-route" in document["paths"]
        assert application.openapi() is document
    finally:
        await application.state.database.dispose()


@pytest.mark.anyio
async def test_api_has_no_duplicate_method_and_path_registrations() -> None:
    application = create_app(settings=TEST_SETTINGS)
    registrations: dict[tuple[str, str], str] = {}
    normalized_registrations: dict[tuple[str, str], tuple[str, str]] = {}
    try:
        for route in application.routes:
            effective_routes: list[Any]
            if isinstance(route, APIRoute):
                effective_routes = [route]
            else:
                route_contexts = getattr(route, "effective_route_contexts", None)
                if route_contexts is None:
                    continue
                effective_routes = [
                    context
                    for context in route_contexts()
                    if isinstance(getattr(context, "original_route", None), APIRoute)
                ]
            for effective_route in effective_routes:
                path = str(effective_route.path)
                name = str(effective_route.name)
                methods = effective_route.methods or set()
                for method in methods:
                    key = (method, path)
                    normalized_key = (method, re.sub(r"{[^}]+}", "{}", path))
                    previous_normalized = normalized_registrations.get(normalized_key)
                    assert previous_normalized is None, (
                        f"Ambiguous API route {method} {path}: "
                        f"{previous_normalized} and {(path, name)}"
                    )
                    assert key not in registrations, (
                        f"Duplicate API route {method} {path}: {registrations[key]} and {name}"
                    )
                    registrations[key] = name
                    normalized_registrations[normalized_key] = (path, name)

        documented_operation_count = sum(
            1
            for path_item in application.openapi()["paths"].values()
            for method in path_item
            if method.lower()
            in {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
        )
        assert registrations
        assert len(registrations) == documented_operation_count
    finally:
        await application.state.database.dispose()


@pytest.mark.anyio
async def test_production_does_not_publish_openapi_or_interactive_docs() -> None:
    production_settings = Settings(
        app_env="production",
        database_url="postgresql+psycopg://edge:edge@db/edge",
        jwt_secret="production-test-secret-that-is-long-enough",
        mock_payment_enabled=False,
    )
    database = Database(TEST_SETTINGS.database_url)
    application = create_app(settings=production_settings, database=database)
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for path in ("/openapi.json", "/docs", "/redoc"):
                response = await client.get(path)
                assert response.status_code == 404
                assert response.headers["content-type"].startswith("application/problem+json")
    finally:
        await database.dispose()


@pytest.mark.anyio
async def test_unknown_sensitive_request_fields_are_rejected_without_value_echo() -> None:
    application = create_app(settings=TEST_SETTINGS)
    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/auth/token",
                headers={"X-Correlation-ID": "unknown-sensitive-fields"},
                json={
                    "tenant_code": "tenant",
                    "username": "operator",
                    "password": "valid-password-without-digits",
                    "card_number": "4111111111111111",
                    "cvv": "987",
                    "4111111111111111": "opaque",
                },
            )
    finally:
        await application.state.database.dispose()

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["x-correlation-id"] == "unknown-sensitive-fields"
    assert "4111111111111111" not in response.text
    assert "987" not in response.text
    payload = response.json()
    assert payload["title"] == "request_validation_failed"
    assert payload["correlation_id"] == "unknown-sensitive-fields"
    assert {tuple(error["location"]) for error in payload["details"]["errors"]} == {
        ("body", "card_number"),
        ("body", "cvv"),
        ("body", "[REDACTED]"),
    }
    assert all("input" not in error for error in payload["details"]["errors"])


@pytest.mark.anyio
async def test_sensitive_model_validation_failure_does_not_echo_original_value() -> None:
    application = create_app(settings=TEST_SETTINGS)

    @application.post("/api/v1/_test/review-validation")
    async def validate_review(body: ResolveReviewRequest) -> dict[str, bool]:
        return {"accepted": body.notes == ""}

    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/_test/review-validation",
                headers={"X-Correlation-ID": "sensitive-validator"},
                json={
                    "expected_version": 1,
                    "resolution": "NO_FINANCIAL_ACTION",
                    "notes": "CVV=654",
                    "payload": {},
                },
            )
    finally:
        await application.state.database.dispose()

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "654" not in response.text
    payload = response.json()
    assert payload["title"] == "request_validation_failed"
    assert payload["correlation_id"] == "sensitive-validator"
    errors = payload["details"]["errors"]
    assert len(errors) == 1
    assert errors[0]["type"] == "value_error"
    assert errors[0]["location"] == ["body"]
    assert "cardholder authentication data" in errors[0]["message"]


@pytest.mark.anyio
async def test_starlette_http_errors_use_the_same_problem_contract() -> None:
    response = await get("/api/v1/route-that-does-not-exist")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")
    payload = response.json()
    assert payload["title"] == "not_found"
    assert payload["detail"] == "Not Found"
    assert payload["status"] == 404
    assert payload["instance"] == "/api/v1/route-that-does-not-exist"
    assert payload["correlation_id"] == response.headers["x-correlation-id"]
    assert payload["details"] == {}


@pytest.mark.anyio
async def test_starlette_http_exception_detail_cannot_echo_sensitive_values() -> None:
    application = create_app(settings=TEST_SETTINGS)

    @application.get("/api/v1/_test/sensitive-http-error")
    async def fail_with_sensitive_http_exception() -> None:
        raise HTTPException(
            status_code=400,
            detail={"card_number": "4111111111111111", "cvv": "321"},
        )

    transport = ASGITransport(app=application)
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/_test/sensitive-http-error")
    finally:
        await application.state.database.dispose()

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "4111111111111111" not in response.text
    assert "321" not in response.text
    payload = response.json()
    assert payload["title"] == "bad_request"
    assert payload["detail"] == "Bad Request"
    assert payload["details"] == {}
