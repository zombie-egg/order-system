from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import KioskDependency, Principal, SessionDependency, require_permission
from app.core.enums import PermissionCode
from app.modules.catalog.schemas import (
    CreateCategoryRequest,
    CreateOptionGroupRequest,
    CreatePriceBookRequest,
    CreateProductRequest,
    ResourceCreatedResponse,
    SetProductAvailabilityRequest,
    StoreCatalogResponse,
)
from app.modules.catalog.service import (
    create_category,
    create_option_group,
    create_price_book,
    create_product,
    get_store_catalog,
    set_product_availability,
)

router = APIRouter(tags=["catalog"])
admin_router = APIRouter(prefix="/admin/catalog", tags=["admin-catalog"])

CatalogWritePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.CATALOG_WRITE.value))
]
CatalogTenantWritePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.CATALOG_TENANT_WRITE.value))
]


@router.get(
    "/kiosk/catalog",
    response_model=StoreCatalogResponse,
    operation_id="get_kiosk_catalog",
)
async def get_catalog(
    session: SessionDependency,
    kiosk_principal: KioskDependency,
    locale: Annotated[str, Query(min_length=2, max_length=20)] = "nl-NL",
) -> StoreCatalogResponse:
    return await get_store_catalog(session, kiosk_principal.store_id, locale)


@admin_router.post(
    "/categories",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_catalog_category",
)
async def post_category(
    request: CreateCategoryRequest,
    session: SessionDependency,
    principal: CatalogTenantWritePrincipal,
) -> ResourceCreatedResponse:
    category = await create_category(session, principal, request)
    return ResourceCreatedResponse(id=category.id)


@admin_router.post(
    "/option-groups",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_catalog_option_group",
)
async def post_option_group(
    request: CreateOptionGroupRequest,
    session: SessionDependency,
    principal: CatalogTenantWritePrincipal,
) -> ResourceCreatedResponse:
    group = await create_option_group(session, principal, request)
    return ResourceCreatedResponse(id=group.id)


@admin_router.post(
    "/products",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_catalog_product",
)
async def post_product(
    request: CreateProductRequest,
    session: SessionDependency,
    principal: CatalogTenantWritePrincipal,
) -> ResourceCreatedResponse:
    product = await create_product(session, principal, request)
    return ResourceCreatedResponse(id=product.id)


@admin_router.patch(
    "/stores/{store_id}/products/{product_id}/availability",
    response_model=ResourceCreatedResponse,
    operation_id="set_store_product_availability",
)
async def patch_availability(
    store_id: UUID,
    product_id: UUID,
    request: SetProductAvailabilityRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    availability = await set_product_availability(
        session,
        principal,
        store_id,
        product_id,
        available=request.available,
        expected_version=request.expected_version,
    )
    return ResourceCreatedResponse(id=availability.product_id)


@admin_router.post(
    "/price-books",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_price_book",
)
async def post_price_book(
    request: CreatePriceBookRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    price_book = await create_price_book(session, principal, request)
    return ResourceCreatedResponse(id=price_book.id)
