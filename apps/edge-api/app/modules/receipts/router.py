from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies import (
    KioskDependency,
    Principal,
    SessionDependency,
    require_permission,
)
from app.core.enums import PermissionCode
from app.modules.receipts.schemas import (
    KioskReceiptResponse,
    ReceiptResponse,
    to_kiosk_receipt_response,
)
from app.modules.receipts.service import (
    get_refund_receipt_for_staff,
    get_sale_receipt_for_staff,
    list_receipts_for_kiosk_order,
)

router = APIRouter(tags=["receipts"])
admin_router = APIRouter(prefix="/admin/receipts", tags=["admin-receipts"])

ReportReadPrincipal = Annotated[
    Principal, Depends(require_permission(PermissionCode.REPORT_READ.value))
]


@router.get(
    "/kiosk/orders/{order_id}/receipts",
    response_model=list[KioskReceiptResponse],
    operation_id="list_kiosk_order_receipts",
)
async def get_receipts(
    order_id: UUID,
    session: SessionDependency,
    kiosk_principal: KioskDependency,
) -> list[KioskReceiptResponse]:
    receipts = await list_receipts_for_kiosk_order(
        session,
        kiosk_id=kiosk_principal.kiosk_id,
        order_id=order_id,
    )
    return [to_kiosk_receipt_response(receipt) for receipt in receipts]


@admin_router.get(
    "/sales/{receipt_id}",
    response_model=ReceiptResponse,
    operation_id="get_sale_receipt",
)
async def get_sale_receipt(
    receipt_id: UUID,
    session: SessionDependency,
    principal: ReportReadPrincipal,
) -> ReceiptResponse:
    return await get_sale_receipt_for_staff(session, principal, receipt_id)


@admin_router.get(
    "/refunds/{receipt_id}",
    response_model=ReceiptResponse,
    operation_id="get_refund_receipt",
)
async def get_refund_receipt(
    receipt_id: UUID,
    session: SessionDependency,
    principal: ReportReadPrincipal,
) -> ReceiptResponse:
    return await get_refund_receipt_for_staff(session, principal, receipt_id)
