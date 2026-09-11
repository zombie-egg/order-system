from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OrderStatus, PaymentStatus, ReceiptType, RefundStatus
from app.core.errors import ConflictError, NotFoundError
from app.core.principals import Principal
from app.modules.audit.service import canonical_hash
from app.modules.ordering.models import OrderItem, OrderItemOption, OrderTaxLine, SalesOrder
from app.modules.organization.models import LegalEntity, Store
from app.modules.payments.models import Refund
from app.modules.receipts.models import Receipt
from app.modules.receipts.schemas import ReceiptResponse
from app.persistence.base import utc_now


async def create_sale_receipt(session: AsyncSession, order: SalesOrder) -> Receipt:
    existing = await session.scalar(
        select(Receipt).where(
            Receipt.order_id == order.id,
            Receipt.receipt_type == ReceiptType.SALE,
        )
    )
    if existing is not None:
        return existing
    if (
        order.status not in {OrderStatus.CONFIRMED, OrderStatus.CLOSED}
        or order.payment_status != PaymentStatus.PAID
        or order.paid_minor != order.total_minor
    ):
        raise ConflictError(
            "sale_receipt_not_ready",
            "A sale receipt can only be generated for a fully paid confirmed order",
        )
    store_row = (
        await session.execute(
            select(Store, LegalEntity)
            .join(LegalEntity, LegalEntity.id == Store.legal_entity_id)
            .where(Store.id == order.store_id)
        )
    ).one()
    store, legal_entity = store_row
    items = list(
        (
            await session.scalars(
                select(OrderItem)
                .where(OrderItem.order_id == order.id)
                .order_by(OrderItem.line_number)
            )
        ).all()
    )
    item_ids = [item.id for item in items]
    options_by_item: dict[UUID, list[dict[str, Any]]] = {item_id: [] for item_id in item_ids}
    if item_ids:
        for option in (
            await session.scalars(
                select(OrderItemOption)
                .where(OrderItemOption.order_item_id.in_(item_ids))
                .order_by(OrderItemOption.order_item_id, OrderItemOption.option_number)
            )
        ).all():
            options_by_item[option.order_item_id].append(
                {
                    "group_name": option.group_name_snapshot,
                    "name": option.name_snapshot,
                    "price_delta_minor": option.price_delta_minor,
                }
            )
    tax_lines = list(
        (
            await session.scalars(
                select(OrderTaxLine)
                .where(OrderTaxLine.order_id == order.id)
                .order_by(OrderTaxLine.tax_category_code, OrderTaxLine.tax_rate_ppm)
            )
        ).all()
    )
    document: dict[str, Any] = {
        "schema_version": 1,
        "receipt_type": ReceiptType.SALE.value,
        "legal_entity": {
            "name": legal_entity.name,
            "vat_number": legal_entity.vat_number,
            "country_code": legal_entity.country_code,
        },
        "store": {"code": store.code, "name": store.name},
        "order": {
            "id": str(order.id),
            "order_number": order.order_number,
            "display_number": order.display_number,
            "business_date": order.business_date.isoformat(),
            "confirmed_at": order.confirmed_at.isoformat() if order.confirmed_at else None,
            "fulfillment_type": order.fulfillment_type.value,
        },
        "currency": order.currency,
        "prices_include_tax": order.prices_include_tax,
        "amounts": {
            "subtotal_minor": order.subtotal_minor,
            "discount_minor": order.discount_minor,
            "net_minor": order.net_minor,
            "tax_minor": order.tax_minor,
            "total_minor": order.total_minor,
            "paid_minor": order.paid_minor,
            "packaging_fee_minor": order.packaging_fee_minor,
        },
        "items": [
            {
                "line_number": item.line_number,
                "sku": item.sku_snapshot,
                "name": item.name_snapshot,
                "quantity": item.quantity,
                "line_total_minor": item.line_total_minor,
                "tax_rate_ppm": item.tax_rate_ppm,
                "options": options_by_item[item.id],
            }
            for item in items
        ],
        "tax_lines": [
            {
                "tax_category_code": line.tax_category_code,
                "tax_rate_ppm": line.tax_rate_ppm,
                "taxable_minor": line.taxable_minor,
                "tax_minor": line.tax_minor,
            }
            for line in tax_lines
        ],
    }
    receipt = Receipt(
        store_id=order.store_id,
        order_id=order.id,
        receipt_type=ReceiptType.SALE,
        receipt_number=order.order_number,
        business_date=order.business_date,
        locale=order.locale,
        currency=order.currency,
        document_snapshot=document,
        content_hash=canonical_hash(document),
        generated_at=utc_now(),
    )
    session.add(receipt)
    await session.flush()
    return receipt


async def create_refund_receipt(
    session: AsyncSession,
    order: SalesOrder,
    refund: Refund,
) -> Receipt:
    existing = await session.scalar(select(Receipt).where(Receipt.refund_id == refund.id))
    if existing is not None:
        return existing
    if (
        refund.order_id != order.id
        or refund.status != RefundStatus.SUCCEEDED
        or refund.completed_at is None
        or refund.currency != order.currency
    ):
        raise ConflictError(
            "refund_receipt_not_ready",
            "A refund receipt requires a provider-confirmed refund for this order",
        )
    document: dict[str, Any] = {
        "schema_version": 1,
        "receipt_type": ReceiptType.REFUND.value,
        "order_id": str(order.id),
        "order_number": order.order_number,
        "refund_id": str(refund.id),
        "reason_code": refund.reason_code,
        "amount_minor": refund.amount_minor,
        "currency": refund.currency,
        "psp_reference": refund.psp_reference,
        "completed_at": refund.completed_at.isoformat() if refund.completed_at else None,
    }
    receipt = Receipt(
        store_id=order.store_id,
        order_id=order.id,
        refund_id=refund.id,
        receipt_type=ReceiptType.REFUND,
        receipt_number=f"R-{order.business_date:%Y%m%d}-{refund.id.hex.upper()}",
        business_date=order.business_date,
        locale=order.locale,
        currency=order.currency,
        document_snapshot=document,
        content_hash=canonical_hash(document),
        generated_at=utc_now(),
    )
    session.add(receipt)
    await session.flush()
    return receipt


async def list_receipts_for_kiosk_order(
    session: AsyncSession,
    *,
    kiosk_id: UUID,
    order_id: UUID,
) -> list[ReceiptResponse]:
    order = await session.scalar(
        select(SalesOrder).where(SalesOrder.id == order_id, SalesOrder.kiosk_id == kiosk_id)
    )
    if order is None:
        raise NotFoundError("sales_order", str(order_id))
    receipts = list(
        (
            await session.scalars(
                select(Receipt).where(Receipt.order_id == order.id).order_by(Receipt.generated_at)
            )
        ).all()
    )
    return [to_receipt_response(receipt) for receipt in receipts]


async def get_sale_receipt_for_staff(
    session: AsyncSession,
    principal: Principal,
    receipt_id: UUID,
) -> ReceiptResponse:
    receipt = await session.scalar(
        select(Receipt)
        .join(
            SalesOrder,
            (SalesOrder.id == Receipt.order_id) & (SalesOrder.store_id == Receipt.store_id),
        )
        .where(
            Receipt.id == receipt_id,
            Receipt.receipt_type == ReceiptType.SALE,
            Receipt.refund_id.is_(None),
            Receipt.store_id.in_(principal.store_ids),
            SalesOrder.tenant_id == principal.tenant_id,
        )
    )
    if receipt is None:
        raise NotFoundError("sale_receipt", str(receipt_id))
    return to_receipt_response(receipt)


async def get_refund_receipt_for_staff(
    session: AsyncSession,
    principal: Principal,
    receipt_id: UUID,
) -> ReceiptResponse:
    receipt = await session.scalar(
        select(Receipt)
        .join(Refund, Refund.id == Receipt.refund_id)
        .join(
            SalesOrder,
            (SalesOrder.id == Receipt.order_id) & (SalesOrder.store_id == Receipt.store_id),
        )
        .where(
            Receipt.id == receipt_id,
            Receipt.receipt_type == ReceiptType.REFUND,
            Receipt.store_id.in_(principal.store_ids),
            Refund.order_id == Receipt.order_id,
            SalesOrder.tenant_id == principal.tenant_id,
        )
    )
    if receipt is None:
        raise NotFoundError("refund_receipt", str(receipt_id))
    return to_receipt_response(receipt)


def to_receipt_response(receipt: Receipt) -> ReceiptResponse:
    if canonical_hash(receipt.document_snapshot) != receipt.content_hash:
        raise ConflictError(
            "receipt_integrity_failed",
            "The stored receipt snapshot no longer matches its integrity hash",
        )
    return ReceiptResponse(
        id=receipt.id,
        order_id=receipt.order_id,
        refund_id=receipt.refund_id,
        receipt_type=receipt.receipt_type,
        receipt_number=receipt.receipt_number,
        locale=receipt.locale,
        currency=receipt.currency,
        document=deepcopy(receipt.document_snapshot),
        content_hash=receipt.content_hash,
        generated_at=receipt.generated_at,
        printed_at=receipt.printed_at,
    )
