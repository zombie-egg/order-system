from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.errors import DomainError

api_router = APIRouter()


def disable_response_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


class HealthResponse(BaseModel):
    status: Literal["alive", "ready"]
    service: str
    version: str


class VersionResponse(BaseModel):
    service: str
    version: str
    environment: str
    country: str


@api_router.get(
    "/health/live",
    response_model=HealthResponse,
    tags=["technical"],
    operation_id="get_liveness",
)
async def live(response: Response) -> HealthResponse:
    disable_response_caching(response)
    settings = get_settings()
    return HealthResponse(
        status="alive",
        service=settings.app_name,
        version=settings.app_version,
    )


@api_router.get(
    "/health/ready",
    response_model=HealthResponse,
    tags=["technical"],
    operation_id="get_readiness",
)
async def ready(response: Response, request: Request) -> HealthResponse:
    disable_response_caching(response)
    settings = get_settings()
    try:
        await request.app.state.database.ping()
    except Exception as exc:
        raise DomainError(
            "database_unavailable",
            "Database readiness check failed",
            status_code=503,
        ) from exc
    return HealthResponse(
        status="ready",
        service=settings.app_name,
        version=settings.app_version,
    )


@api_router.get(
    "/version",
    response_model=VersionResponse,
    tags=["technical"],
    operation_id="get_version",
)
async def version(response: Response) -> VersionResponse:
    disable_response_caching(response)
    settings = get_settings()
    return VersionResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        country=settings.default_country,
    )
