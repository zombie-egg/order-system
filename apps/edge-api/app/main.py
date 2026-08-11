from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import DomainError
from app.core.logging import configure_logging
from app.core.request_context import correlation_id_context
from app.persistence.database import Database


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings: Settings = application.state.settings
    configure_logging(settings.log_level, settings.log_format)
    logger = logging.getLogger(__name__)
    logger.info(
        "edge_api_started",
        extra={"app_version": settings.app_version, "app_env": settings.app_env},
    )
    try:
        yield
    finally:
        await application.state.database.dispose()
        logger.info("edge_api_stopped")


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=("Netherlands-first kiosk ordering, payment, and manual fulfillment Edge API."),
        lifespan=lifespan,
    )
    application.state.settings = resolved_settings
    application.state.database = database or Database(resolved_settings.database_url)
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
            "X-Correlation-ID",
        ],
    )

    @application.middleware("http")
    async def correlation_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get("X-Correlation-ID", "")
        correlation_id = incoming[:80] if incoming else str(uuid4())
        token = correlation_id_context.set(correlation_id)
        try:
            response = await call_next(request)
            response.headers["X-Correlation-ID"] = correlation_id
            return response
        finally:
            correlation_id_context.reset(token)

    @application.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        correlation_id = correlation_id_context.get()
        headers = {"X-Correlation-ID": correlation_id or ""}
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = "Bearer"
        return JSONResponse(
            status_code=exc.status_code,
            headers=headers,
            content={
                "type": f"urn:smart-drink:error:{exc.code}",
                "title": exc.code,
                "status": exc.status_code,
                "detail": exc.message,
                "instance": str(request.url.path),
                "correlation_id": correlation_id,
                "details": exc.details,
            },
        )

    application.include_router(api_router, prefix=resolved_settings.api_prefix)
    return application


app = create_app()
