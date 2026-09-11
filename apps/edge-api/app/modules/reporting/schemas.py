from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.core.enums import FulfillmentStatus, RefundStatus


class StoreOperationsSummary(BaseModel):
    store_id: UUID
    open_orders: int
    open_tickets: int
    open_manual_reviews: int
    unknown_payments: int
    paid_orders_without_tickets: int
    pending_outbox_events: int


class ReportPeriodResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: UUID | None = None
    start_at: datetime
    end_at: datetime


class SalesSummaryResponse(ReportPeriodResponse):
    currency: str
    order_count: int
    gross_sales_minor: int
    discount_minor: int
    net_minor: int
    tax_minor: int
    paid_minor: int
    refunded_minor: int
    net_collected_minor: int


class RefundSummaryResponse(ReportPeriodResponse):
    currency: str
    refund_count: int
    requested_minor: int
    succeeded_minor: int
    status_counts: dict[RefundStatus, int]
    status_amounts_minor: dict[RefundStatus, int]


class FulfillmentSummaryResponse(ReportPeriodResponse):
    ticket_count: int
    status_counts: dict[FulfillmentStatus, int]
    average_seconds_to_acknowledge: int | None
    average_seconds_to_ready: int | None
    average_seconds_ready_to_collect: int | None


class ReconciliationSummaryResponse(ReportPeriodResponse):
    run_count: int
    completed_run_count: int
    failed_run_count: int
    open_issue_count: int
    critical_open_issue_count: int
    latest_run_status: str | None
    latest_run_started_at: datetime | None
    latest_run_completed_at: datetime | None


class TopProductItem(BaseModel):
    product_id: UUID
    sku: str
    name: str
    quantity: int
    revenue_minor: int
    currency: str


class TopProductsResponse(BaseModel):
    store_ids: list[UUID]
    start_at: datetime
    end_at: datetime
    order_by: str
    limit: int
    currency: str
    items: list[TopProductItem]


class StoreSalesSnapshot(BaseModel):
    store_id: UUID | None = None
    store_code: str | None = None
    store_name: str | None = None
    order_count: int
    gross_sales_minor: int
    discount_minor: int
    net_sales_minor: int
    tax_minor: int
    refunded_minor: int
    net_collected_minor: int
    ticket_count: int


class TrendBucket(BaseModel):
    bucket: str
    order_count: int
    gross_sales_minor: int
    refunded_minor: int
    ticket_count: int


class MultiStoreSummaryResponse(ReportPeriodResponse):
    period: str
    currency: str
    stores: list[StoreSalesSnapshot]
    totals: StoreSalesSnapshot
    trend: list[TrendBucket]


class DashboardKpiStore(BaseModel):
    store_id: UUID | None = None
    store_code: str | None = None
    store_name: str | None = None
    today_order_count: int
    today_revenue_minor: int
    open_tickets: int
    open_manual_reviews: int
    unknown_payments: int


class DashboardKpiResponse(BaseModel):
    business_date: str
    currency: str
    stores: list[DashboardKpiStore]
    totals: DashboardKpiStore
