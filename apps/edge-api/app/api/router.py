from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.core.errors import DomainError
from app.modules.audit.router import router as audit_router
from app.modules.catalog.router import admin_router as catalog_admin_router
from app.modules.catalog.router import router as catalog_router
from app.modules.identity.router import admin_router as identity_admin_router
from app.modules.identity.router import router as identity_router
from app.modules.kitchen_fulfillment.router import router as fulfillment_router
from app.modules.manual_review.router import router as manual_review_router
from app.modules.ordering.router import admin_router as ordering_admin_router
from app.modules.ordering.router import router as ordering_router
from app.modules.organization.router import admin_router as organization_admin_router
from app.modules.organization.router import router as organization_router
from app.modules.payments.router import admin_router as payments_admin_router
from app.modules.payments.router import router as payments_router
from app.modules.pricing_tax.router import admin_router as pricing_admin_router
from app.modules.pricing_tax.router import router as pricing_router
from app.modules.receipts.router import admin_router as receipts_admin_router
from app.modules.receipts.router import router as receipts_router
from app.modules.reporting.router import router as reporting_router

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
async def live(response: Response, request: Request) -> HealthResponse:
    disable_response_caching(response)
    settings = request.app.state.settings
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
    settings = request.app.state.settings
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
async def version(response: Response, request: Request) -> VersionResponse:
    disable_response_caching(response)
    settings = request.app.state.settings
    return VersionResponse(
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.app_env,
        country=settings.default_country,
    )


api_router.include_router(identity_router)
api_router.include_router(identity_admin_router)
api_router.include_router(organization_router)
api_router.include_router(organization_admin_router)
api_router.include_router(catalog_router)
api_router.include_router(catalog_admin_router)
api_router.include_router(pricing_router)
api_router.include_router(pricing_admin_router)
api_router.include_router(ordering_router)
api_router.include_router(ordering_admin_router)
api_router.include_router(payments_router)
api_router.include_router(payments_admin_router)
api_router.include_router(fulfillment_router)
api_router.include_router(manual_review_router)
api_router.include_router(receipts_router)
api_router.include_router(receipts_admin_router)
api_router.include_router(reporting_router)
api_router.include_router(audit_router)
