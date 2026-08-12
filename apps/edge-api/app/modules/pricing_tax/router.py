from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.dependencies import (
    KioskDependency,
    Principal,
    SessionDependency,
    SettingsDependency,
    require_permission,
)
from app.core.enums import PermissionCode
from app.modules.catalog.schemas import ResourceCreatedResponse
from app.modules.organization.service import get_store_for_tenant
from app.modules.pricing_tax.schemas import (
    CreatePromotionRequest,
    CreateQuoteRequest,
    CreateTaxPolicyRequest,
    QuoteResponse,
)
from app.modules.pricing_tax.service import create_promotion, create_quote, create_tax_policy

router = APIRouter(tags=["pricing"])
admin_router = APIRouter(prefix="/admin/pricing", tags=["admin-pricing"])

CatalogWritePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.CATALOG_WRITE.value))
]
CatalogTenantWritePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.CATALOG_TENANT_WRITE.value))
]


@router.post(
    "/kiosk/quotes",
    response_model=QuoteResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_kiosk_quote",
)
async def post_quote(
    request: CreateQuoteRequest,
    session: SessionDependency,
    settings: SettingsDependency,
    kiosk_principal: KioskDependency,
) -> QuoteResponse:
    return await create_quote(
        session,
        settings,
        store_id=kiosk_principal.store_id,
        kiosk_id=kiosk_principal.kiosk_id,
        request=request,
    )


@admin_router.post(
    "/tax-policies",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_tax_policy",
)
async def post_tax_policy(
    request: CreateTaxPolicyRequest,
    session: SessionDependency,
    principal: CatalogTenantWritePrincipal,
) -> ResourceCreatedResponse:
    store = await get_store_for_tenant(session, principal, request.store_id)
    policy = await create_tax_policy(session, principal, store, request)
    return ResourceCreatedResponse(id=policy.id)


@admin_router.post(
    "/promotions",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_promotion",
)
async def post_promotion(
    request: CreatePromotionRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    await get_store_for_tenant(session, principal, request.store_id)
    promotion = await create_promotion(session, principal, request)
    return ResourceCreatedResponse(id=promotion.id)
