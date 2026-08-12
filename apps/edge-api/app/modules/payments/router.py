from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from app.api.dependencies import (
    KioskDependency,
    Principal,
    SessionDependency,
    get_database,
    require_permission,
)
from app.core.enums import PermissionCode
from app.modules.ordering.schemas import KioskOrderResponse, to_kiosk_order_response
from app.modules.payments.providers import PaymentAdapter
from app.modules.payments.schemas import RefundResponse
from app.modules.payments.service import (
    execute_authorization,
    execute_refund,
    list_refunds_for_stores,
)
from app.persistence.database import Database

router = APIRouter(tags=["payments"])
admin_router = APIRouter(prefix="/admin/payments", tags=["admin-payments"])

PaymentReadPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.PAYMENT_READ.value))
]
ReviewResolvePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.REVIEW_RESOLVE.value))
]
PaymentReconcilePrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.PAYMENT_RECONCILE.value))
]
DatabaseDependency = Annotated[Database, Depends(get_database)]


def _adapter(request: Request) -> PaymentAdapter:
    return cast(PaymentAdapter, request.app.state.payment_adapter)


@router.post(
    "/kiosk/payment-attempts/{attempt_id}/execute",
    response_model=KioskOrderResponse,
    operation_id="execute_kiosk_payment",
)
async def post_execute_payment(
    attempt_id: UUID,
    request: Request,
    database: DatabaseDependency,
    kiosk_principal: KioskDependency,
) -> KioskOrderResponse:
    order = await execute_authorization(
        database,
        _adapter(request),
        kiosk_id=kiosk_principal.kiosk_id,
        attempt_id=attempt_id,
    )
    return to_kiosk_order_response(order)


@router.post(
    "/kiosk/payment-attempts/{attempt_id}/reconcile",
    response_model=KioskOrderResponse,
    operation_id="reconcile_kiosk_payment",
)
async def post_reconcile_payment(
    attempt_id: UUID,
    request: Request,
    database: DatabaseDependency,
    kiosk_principal: KioskDependency,
) -> KioskOrderResponse:
    order = await execute_authorization(
        database,
        _adapter(request),
        kiosk_id=kiosk_principal.kiosk_id,
        attempt_id=attempt_id,
        reconcile=True,
    )
    return to_kiosk_order_response(order)


@admin_router.get(
    "/refunds",
    response_model=list[RefundResponse],
    operation_id="list_refunds",
)
async def get_refunds(
    session: SessionDependency,
    principal: PaymentReadPrincipal,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RefundResponse]:
    return await list_refunds_for_stores(session, principal.store_ids, limit=limit)


@admin_router.post(
    "/refunds/{refund_id}/execute",
    response_model=RefundResponse,
    operation_id="execute_refund",
)
async def post_execute_refund(
    refund_id: UUID,
    request: Request,
    database: DatabaseDependency,
    principal: ReviewResolvePrincipal,
) -> RefundResponse:
    return await execute_refund(
        database,
        _adapter(request),
        principal,
        refund_id=refund_id,
    )


@admin_router.post(
    "/refunds/{refund_id}/reconcile",
    response_model=RefundResponse,
    operation_id="reconcile_refund",
)
async def post_reconcile_refund(
    refund_id: UUID,
    request: Request,
    database: DatabaseDependency,
    principal: PaymentReconcilePrincipal,
) -> RefundResponse:
    return await execute_refund(
        database,
        _adapter(request),
        principal,
        refund_id=refund_id,
        reconcile=True,
    )
