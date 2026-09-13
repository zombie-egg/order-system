from __future__ import annotations

import base64
import binascii
from pathlib import Path
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.dependencies import KioskDependency, Principal, SessionDependency, require_permission
from app.core.enums import PermissionCode
from app.core.errors import DomainError
from app.modules.catalog.schemas import (
    AdminCategoryResponse,
    AdminOptionGroupResponse,
    AdminProductListResponse,
    CreateCategoryRequest,
    CreateOptionGroupRequest,
    CreateOptionValueInput,
    CreatePriceBookRequest,
    CreateProductRequest,
    ProductImageUploadRequest,
    ProductImageUploadResponse,
    ResourceCreatedResponse,
    SetProductAvailabilityRequest,
    SetProductOptionPriceRequest,
    SetProductPriceRequest,
    StoreCatalogResponse,
    UpdateOptionGroupRequest,
    UpdateOptionValueRequest,
    UpdateProductRequest,
)
from app.modules.catalog.service import (
    create_category,
    create_option_group,
    create_option_value,
    create_price_book,
    create_product,
    delete_option_group,
    delete_product,
    get_store_catalog,
    list_admin_categories,
    list_admin_option_groups,
    list_admin_products,
    set_product_availability,
    set_product_option_price,
    set_product_price,
    update_option_group,
    update_option_value,
    update_product,
)

router = APIRouter(tags=["catalog"])
admin_router = APIRouter(prefix="/admin/catalog", tags=["admin-catalog"])

CatalogWritePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.CATALOG_WRITE.value))
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
    principal: CatalogWritePrincipal,
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
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    group = await create_option_group(session, principal, request)
    return ResourceCreatedResponse(id=group.id)


@admin_router.get(
    "/stores/{store_id}/option-groups",
    response_model=list[AdminOptionGroupResponse],
    operation_id="list_admin_catalog_option_groups",
)
async def get_admin_option_groups(
    store_id: UUID,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> list[AdminOptionGroupResponse]:
    return await list_admin_option_groups(session, principal, store_id)


@admin_router.patch(
    "/stores/{store_id}/option-groups/{group_id}",
    response_model=ResourceCreatedResponse,
    operation_id="update_catalog_option_group",
)
async def patch_option_group(
    store_id: UUID,
    group_id: UUID,
    request: UpdateOptionGroupRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    group = await update_option_group(session, principal, store_id, group_id, request)
    return ResourceCreatedResponse(id=group.id)


@admin_router.delete(
    "/stores/{store_id}/option-groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="delete_catalog_option_group",
)
async def delete_admin_option_group(
    store_id: UUID,
    group_id: UUID,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> None:
    await delete_option_group(session, principal, store_id, group_id)


@admin_router.post(
    "/stores/{store_id}/option-groups/{group_id}/values",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_catalog_option_value",
)
async def post_option_value(
    store_id: UUID,
    group_id: UUID,
    request: CreateOptionValueInput,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    value = await create_option_value(session, principal, store_id, group_id, request)
    return ResourceCreatedResponse(id=value.id)


@admin_router.patch(
    "/stores/{store_id}/option-groups/{group_id}/values/{value_id}",
    response_model=ResourceCreatedResponse,
    operation_id="update_catalog_option_value",
)
async def patch_option_value(
    store_id: UUID,
    group_id: UUID,
    value_id: UUID,
    request: UpdateOptionValueRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    value = await update_option_value(session, principal, store_id, group_id, value_id, request)
    return ResourceCreatedResponse(id=value.id)


@admin_router.post(
    "/products",
    response_model=ResourceCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_catalog_product",
)
async def post_product(
    request: CreateProductRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
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
    principal: CatalogWritePrincipal,
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


@admin_router.get(
    "/stores/{store_id}/products",
    response_model=AdminProductListResponse,
    operation_id="list_admin_catalog_products",
)
async def get_admin_products(
    store_id: UUID,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> AdminProductListResponse:
    return await list_admin_products(session, principal, store_id)


@admin_router.get(
    "/stores/{store_id}/categories",
    response_model=list[AdminCategoryResponse],
    operation_id="list_admin_catalog_categories",
)
async def get_admin_categories(
    store_id: UUID,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> list[AdminCategoryResponse]:
    return await list_admin_categories(session, principal, store_id)


@admin_router.patch(
    "/stores/{store_id}/products/{product_id}",
    response_model=ResourceCreatedResponse,
    operation_id="update_catalog_product",
)
async def patch_admin_product(
    store_id: UUID,
    product_id: UUID,
    request: UpdateProductRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    product = await update_product(session, principal, store_id, product_id, request)
    return ResourceCreatedResponse(id=product.id)


@admin_router.put(
    "/stores/{store_id}/products/{product_id}/price",
    response_model=ResourceCreatedResponse,
    operation_id="set_catalog_product_price",
)
async def put_product_price(
    store_id: UUID,
    product_id: UUID,
    request: SetProductPriceRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    await set_product_price(session, principal, store_id, product_id, request)
    return ResourceCreatedResponse(id=product_id)


@admin_router.put(
    "/stores/{store_id}/products/{product_id}/options/{value_id}/price",
    response_model=ResourceCreatedResponse,
    operation_id="set_catalog_product_option_price",
)
async def put_product_option_price(
    store_id: UUID,
    product_id: UUID,
    value_id: UUID,
    request: SetProductOptionPriceRequest,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    await set_product_option_price(session, principal, store_id, product_id, value_id, request)
    return ResourceCreatedResponse(id=value_id)


@admin_router.delete(
    "/stores/{store_id}/products/{product_id}",
    response_model=ResourceCreatedResponse,
    operation_id="delete_catalog_product",
)
async def delete_admin_product(
    store_id: UUID,
    product_id: UUID,
    session: SessionDependency,
    principal: CatalogWritePrincipal,
) -> ResourceCreatedResponse:
    product = await delete_product(session, principal, store_id, product_id)
    return ResourceCreatedResponse(id=product.id)
