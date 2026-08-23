from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies import KioskDependency, Principal, SessionDependency, require_permission
from app.core.errors import DomainError
from app.core.enums import PermissionCode
from app.modules.catalog.schemas import (
    CreateCategoryRequest,
    CreateOptionGroupRequest,
    CreatePriceBookRequest,
    CreateProductRequest,
    ProductImageUploadRequest,
    ProductImageUploadResponse,
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

IMAGE_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
MAX_PRODUCT_IMAGE_BYTES = 5 * 1024 * 1024


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


@admin_router.post(
    "/product-images",
    response_model=ProductImageUploadResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="upload_catalog_product_image",
)
async def upload_product_image(
    request: ProductImageUploadRequest,
    http_request: Request,
    principal: CatalogTenantWritePrincipal,
) -> ProductImageUploadResponse:
    """Store a single admin-selected product image for use in a catalog card.

    The client sends a data URL so this endpoint remains compatible with the
    JSON-only edge API and does not require multipart form parsing.
    """
    try:
        header, encoded = request.image_data.split(",", 1)
        mime_type = header.removeprefix("data:").removesuffix(";base64")
    except ValueError as exc:
        raise DomainError("invalid_image", "图片格式无效。", status_code=422) from exc
    suffix = IMAGE_MIME_TYPES.get(mime_type)
    if not suffix or not header.endswith(";base64"):
        raise DomainError("unsupported_image", "仅支持 JPG、PNG 或 WebP 图片。", status_code=422)
    try:
        image_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DomainError("invalid_image", "图片数据无效。", status_code=422) from exc
    if not image_bytes or len(image_bytes) > MAX_PRODUCT_IMAGE_BYTES:
        raise DomainError("image_too_large", "图片大小须介于 1 字节和 5MB 之间。", status_code=422)

    filename = f"{principal.tenant_id}-{uuid4().hex}{suffix}"
    media_dir = Path(http_request.app.state.settings.media_storage_dir).resolve()
    product_dir = media_dir / "products"
    product_dir.mkdir(parents=True, exist_ok=True)
    (product_dir / filename).write_bytes(image_bytes)
    base_url = str(http_request.base_url).rstrip("/")
    return ProductImageUploadResponse(image_url=f"{base_url}/media/products/{filename}")


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
