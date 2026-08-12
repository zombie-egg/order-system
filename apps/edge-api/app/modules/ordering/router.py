from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, status

from app.api.dependencies import (
    KioskDependency,
    Principal,
    SessionDependency,
    SettingsDependency,
    require_permission,
)
from app.core.enums import PermissionCode
from app.modules.ordering.schemas import (
    CreateOrderRequest,
    KioskOrderResponse,
    OrderResponse,
    RetryPaymentRequest,
    to_kiosk_order_response,
)
from app.modules.ordering.service import (
    create_order,
    create_retry_payment_attempt,
    get_order_for_kiosk,
    get_order_for_store,
    list_orders_for_stores,
)

router = APIRouter(tags=["orders"])
admin_router = APIRouter(prefix="/admin/orders", tags=["admin-orders"])

OrderReadPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.ORDER_READ.value))
]


@router.post(
    "/kiosk/orders",
    response_model=KioskOrderResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_kiosk_order",
)
async def post_order(
    request: CreateOrderRequest,
    session: SessionDependency,
    settings: SettingsDependency,
    kiosk_principal: KioskDependency,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> KioskOrderResponse:
    order = await create_order(
        session,
        settings,
        kiosk_id=kiosk_principal.kiosk_id,
        store_id=kiosk_principal.store_id,
        quote_id=request.quote_id,
        payment_method=request.payment_method,
        idempotency_key=idempotency_key,
    )
    return to_kiosk_order_response(order)


@router.get(
    "/kiosk/orders/{order_id}",
    response_model=KioskOrderResponse,
    operation_id="get_kiosk_order",
)
async def get_kiosk_order(
    order_id: UUID,
    session: SessionDependency,
    kiosk_principal: KioskDependency,
) -> KioskOrderResponse:
    order = await get_order_for_kiosk(session, kiosk_principal.kiosk_id, order_id)
    return to_kiosk_order_response(order)


@router.post(
    "/kiosk/orders/{order_id}/payment-attempts",
    response_model=KioskOrderResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="retry_kiosk_order_payment",
)
async def post_retry_payment(
    order_id: UUID,
    request: RetryPaymentRequest,
    session: SessionDependency,
    settings: SettingsDependency,
    kiosk_principal: KioskDependency,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
) -> KioskOrderResponse:
    order = await create_retry_payment_attempt(
        session,
        settings,
        kiosk_id=kiosk_principal.kiosk_id,
        store_id=kiosk_principal.store_id,
        order_id=order_id,
        payment_method=request.payment_method,
        idempotency_key=idempotency_key,
    )
    return to_kiosk_order_response(order)


@admin_router.get("", response_model=list[OrderResponse], operation_id="list_store_orders")
async def get_orders(
    session: SessionDependency,
    principal: OrderReadPrincipal,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[OrderResponse]:
    return await list_orders_for_stores(session, principal.store_ids, limit=limit)


@admin_router.get(
    "/{order_id}",
    response_model=OrderResponse,
    operation_id="get_store_order",
)
async def get_order(
    order_id: UUID,
    session: SessionDependency,
    principal: OrderReadPrincipal,
) -> OrderResponse:
    return await get_order_for_store(session, principal.store_ids, order_id)
