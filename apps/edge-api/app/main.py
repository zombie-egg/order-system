from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.api.router import api_router
from app.core.api_models import ProblemDetails
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging
from app.core.request_context import correlation_id_context
from app.core.sensitive_data import redact_sensitive_card_data
from app.modules.identity.service import PasswordVerificationLimiter
from app.modules.payments.providers import (
    DisabledPaymentAdapter,
    MockPaymentAdapter,
    PaymentAdapter,
)
from app.persistence.database import Database

CORRELATION_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,80}$")


def _problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    detail: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    correlation_id = correlation_id_context.get() or str(uuid4())
    response_headers = dict(headers or {})
    response_headers["X-Correlation-ID"] = correlation_id
    return JSONResponse(
        status_code=status_code,
        headers=response_headers,
        media_type="application/problem+json",
        content={
            "type": f"urn:smart-drink:error:{code}",
            "title": code,
            "status": status_code,
            "detail": detail,
            "instance": str(request.url.path),
            "correlation_id": correlation_id,
            "details": details or {},
        },
    )


def _sanitized_validation_errors(exc: RequestValidationError) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for error in exc.errors():
        location = [redact_sensitive_card_data(str(part))[:120] for part in error.get("loc", ())]
        message = redact_sensitive_card_data(str(error.get("msg", "Invalid value")))[:500]
        errors.append(
            {
                "type": str(error.get("type", "validation_error"))[:120],
                "location": location,
                "message": message,
            }
        )
    return errors


def _http_error_code(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        405: "method_not_allowed",
        413: "payload_too_large",
        415: "unsupported_media_type",
        429: "too_many_requests",
    }.get(status_code, "http_error")


def _http_error_detail(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP request failed"


def _documented_problem_responses() -> dict[int | str, dict[str, Any]]:
    return {
        status_code: {
            "description": _http_error_detail(status_code),
            "content": {
                "application/problem+json": {
                    "schema": ProblemDetails.model_json_schema(),
                }
            },
        }
        for status_code in (400, 401, 403, 404, 405, 409, 413, 415, 422, 429, 500, 503)
    }


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings: Settings = application.state.settings
    logger = logging.getLogger(__name__)
    try:
        configure_logging(settings.log_level, settings.log_format)
        logger.info(
            "edge_api_started",
            extra={"app_version": settings.app_version, "app_env": settings.app_env},
        )
        yield
    finally:
        try:
            await application.state.database.dispose()
        finally:
            logger.info("edge_api_stopped")


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    payment_adapter: PaymentAdapter | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    documentation_enabled = resolved_settings.app_env in {"development", "test"}
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=("Netherlands-first kiosk ordering, payment, and manual fulfillment Edge API."),
        lifespan=lifespan,
        responses=_documented_problem_responses(),
        openapi_url="/openapi.json" if documentation_enabled else None,
        docs_url="/docs" if documentation_enabled else None,
        redoc_url="/redoc" if documentation_enabled else None,
    )
    application.state.settings = resolved_settings
    application.state.database = database or Database(resolved_settings.database_url)
    application.state.password_verification_limiter = PasswordVerificationLimiter(
        resolved_settings.login_password_verify_concurrency
    )
    application.state.payment_adapter = payment_adapter or (
        MockPaymentAdapter(resolved_settings.mock_payment_scenario)
        if resolved_settings.mock_payment_enabled
        else DisabledPaymentAdapter()
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=[
            "Accept",
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Endpoint-ID",
            "X-Endpoint-Key",
            "X-Kiosk-ID",
            "X-Kiosk-Key",
            "X-Correlation-ID",
        ],
    )

    @application.middleware("http")
    async def correlation_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("X-Correlation-ID", "")
        correlation_id = incoming if CORRELATION_ID_PATTERN.fullmatch(incoming) else str(uuid4())
        token = correlation_id_context.set(correlation_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            if request.url.path.startswith(resolved_settings.api_prefix):
                response.headers["Cache-Control"] = "no-store"
                response.headers["Pragma"] = "no-cache"
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Referrer-Policy"] = "no-referrer"
            return response
        finally:
            correlation_id_context.reset(token)

    @application.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        headers = dict(getattr(exc, "response_headers", {}))
        authenticate_header = getattr(exc, "authenticate_header", None)
        if exc.status_code == 401 and authenticate_header:
            headers["WWW-Authenticate"] = authenticate_header
        return _problem_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            detail=redact_sensitive_card_data(exc.message),
            details=exc.details,
            headers=headers,
        )

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _problem_response(
            request,
            status_code=422,
            code="request_validation_failed",
            detail="The request did not satisfy the API contract",
            details={"errors": _sanitized_validation_errors(exc)},
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        return _problem_response(
            request,
            status_code=exc.status_code,
            code=_http_error_code(exc.status_code),
            detail=_http_error_detail(exc.status_code),
            headers=dict(exc.headers or {}),
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        correlation_id = correlation_id_context.get() or str(uuid4())
        logging.getLogger(__name__).error(
            "unhandled_request_error",
            extra={
                "correlation_id": correlation_id,
                "request_method": request.method,
                "request_path": redact_sensitive_card_data(request.url.path)[:500],
                "exception_type": type(exc).__name__,
            },
        )
        return _problem_response(
            request,
            status_code=500,
            code="internal_error",
            detail="An unexpected server error occurred",
            headers={"Cache-Control": "no-store", "X-Correlation-ID": correlation_id},
        )

    application.include_router(api_router, prefix=resolved_settings.api_prefix)

    default_openapi = application.openapi

    def openapi_with_composite_device_security() -> dict[str, Any]:
        document = default_openapi()
        paths = document.get("paths", {})
        prefix = resolved_settings.api_prefix.rstrip("/")
        for path, methods in paths.items():
            if path.startswith(f"{prefix}/kiosk/"):
                for operation in methods.values():
                    operation["security"] = [{"KioskDeviceId": [], "KioskDeviceKey": []}]
            elif path == f"{prefix}/fulfillment/heartbeat":
                for operation in methods.values():
                    operation["security"] = [
                        {
                            "FulfillmentEndpointId": [],
                            "FulfillmentEndpointKey": [],
                        }
                    ]
            elif path.startswith(f"{prefix}/fulfillment/tickets"):
                for operation in methods.values():
                    operation["security"] = [
                        {
                            "FulfillmentEndpointId": [],
                            "FulfillmentEndpointKey": [],
                            "StaffBearerAuth": [],
                        }
                    ]
        return document

    application.openapi = openapi_with_composite_device_security  # type: ignore[method-assign]
    return application


app = create_app()
