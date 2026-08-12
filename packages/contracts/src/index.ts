export type UUID = string;
export type IsoDateTime = string;

export type PaymentMethod = 'CARD' | 'CONTACTLESS' | 'APPLE_PAY' | 'GOOGLE_PAY';
export type PaymentStatus =
  | 'UNPAID'
  | 'INITIATED'
  | 'AUTHORIZING'
  | 'PAID'
  | 'FAILED'
  | 'UNKNOWN'
  | 'REFUND_PENDING'
  | 'PARTIALLY_REFUNDED'
  | 'REFUNDED';
export type OrderStatus = 'DRAFT' | 'CONFIRMED' | 'CLOSED' | 'CANCELLED';
export type FulfillmentStatus =
  | 'NOT_RELEASED'
  | 'QUEUED'
  | 'ACKNOWLEDGED'
  | 'PREPARING'
  | 'READY'
  | 'COLLECTED'
  | 'ON_HOLD'
  | 'UNFULFILLABLE'
  | 'CANCELLED';
export type FulfillmentFailureReason =
  | 'OUT_OF_STOCK'
  | 'STAFF_CAPACITY'
  | 'MANUAL_WORKSTATION_EQUIPMENT_FAILURE'
  | 'ORDER_ERROR'
  | 'ALLERGEN_OR_RECIPE_ISSUE'
  | 'STORE_CLOSING'
  | 'OTHER';
export type ReviewStatus = 'OPEN' | 'ASSIGNED' | 'ACTION_PENDING' | 'RESOLVED' | 'CLOSED';
export type ReviewResolution =
  | 'FULL_REFUND'
  | 'PARTIAL_REFUND'
  | 'REMAKE'
  | 'SUBSTITUTION'
  | 'MANUALLY_FULFILLED'
  | 'NO_FINANCIAL_ACTION';
export type RefundStatus = 'PENDING' | 'SUCCEEDED' | 'FAILED' | 'UNKNOWN';

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  errors?: Array<{ location?: string[]; message?: string; type?: string }>;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_at: IsoDateTime;
}

export interface PrincipalResponse {
  user_id: UUID;
  tenant_id: UUID;
  permissions: string[];
  store_ids: UUID[];
}

export interface StoreResponse {
  id: UUID;
  code: string;
  name: string;
  country_code: string;
  currency: string;
  locale: string;
  timezone: string;
  active: boolean;
  version: number;
}

export interface StorePolicyResponse {
  store_id: UUID;
  accepting_orders: boolean;
  max_open_tickets: number;
  kds_heartbeat_seconds: number;
  printer_fallback_enabled: boolean;
  version: number;
}

export interface StoreWithPolicyResponse {
  store: StoreResponse;
  policy: StorePolicyResponse;
}

export interface CatalogOptionValue {
  id: UUID;
  code: string;
  name: string;
  price_delta_minor: number;
}

export interface CatalogOptionGroup {
  id: UUID;
  code: string;
  name: string;
  minimum_selections: number;
  maximum_selections: number;
  values: CatalogOptionValue[];
}

export interface CatalogProduct {
  id: UUID;
  sku: string;
  name: string;
  description: string;
  image_url: string | null;
  price_minor: number;
  currency: string;
  tax_category_code: string;
  allergen_data: Record<string, unknown>;
  option_groups: CatalogOptionGroup[];
}

export interface StoreCatalog {
  store_id: UUID;
  locale: string;
  currency: string;
  price_book_id: UUID;
  categories: Array<{ id: UUID; code: string; name: string; products: CatalogProduct[] }>;
}

export interface QuoteRequest {
  locale: string;
  items: Array<{ product_id: UUID; quantity: number; option_value_ids: UUID[] }>;
  promotion_code?: string | null;
}

export interface QuoteResponse {
  id: UUID;
  status: 'ACTIVE' | 'CONSUMED' | 'EXPIRED' | 'CANCELLED';
  store_id: UUID;
  kiosk_id: UUID;
  currency: string;
  locale: string;
  prices_include_tax: boolean;
  subtotal_minor: number;
  discount_minor: number;
  net_minor: number;
  tax_minor: number;
  total_minor: number;
  expires_at: IsoDateTime;
  items: QuoteItem[];
  tax_lines: Array<{
    tax_category_code: string;
    tax_rate_ppm: number;
    taxable_minor: number;
    tax_minor: number;
  }>;
}

export interface QuoteItem {
  line_number: number;
  product_id: UUID;
  sku: string;
  name: string;
  quantity: number;
  unit_price_minor: number;
  option_total_minor: number;
  discount_minor: number;
  net_minor: number;
  tax_minor: number;
  line_total_minor: number;
  options: Array<{
    option_value_id: UUID;
    group_name: string;
    name: string;
    price_delta_minor: number;
  }>;
  allergen_snapshot: Record<string, unknown>;
}

export interface KioskOrderResponse {
  id: UUID;
  display_number: string;
  status: OrderStatus;
  payment_status: PaymentStatus;
  currency: string;
  locale: string;
  prices_include_tax: boolean;
  subtotal_minor: number;
  discount_minor: number;
  net_minor: number;
  tax_minor: number;
  total_minor: number;
  paid_minor: number;
  refunded_minor: number;
  items: Array<{
    line_number: number;
    name: string;
    quantity: number;
    unit_price_minor: number;
    option_total_minor: number;
    discount_minor: number;
    net_minor: number;
    tax_minor: number;
    line_total_minor: number;
    allergen_snapshot: Record<string, unknown>;
    options: Array<{ group_name: string; name: string; price_delta_minor: number }>;
  }>;
  payment_attempts: Array<{
    id: UUID;
    payment_method: PaymentMethod;
    status: PaymentStatus;
    amount_minor: number;
    currency: string;
  }>;
}

export interface OrderResponse extends Omit<KioskOrderResponse, 'payment_attempts'> {
  store_id: UUID;
  kiosk_id: UUID;
  quote_id: UUID;
  business_date: string;
  order_number: string;
  confirmed_at: IsoDateTime | null;
  closed_at: IsoDateTime | null;
  version: number;
  payment_attempts: Array<{
    id: UUID;
    attempt_number: number;
    provider: string;
    payment_method: PaymentMethod;
    status: PaymentStatus;
    amount_minor: number;
    currency: string;
    psp_reference: string | null;
    failure_code: string | null;
    requested_at: IsoDateTime;
    completed_at: IsoDateTime | null;
    version: number;
  }>;
}

export interface KioskReceiptResponse {
  receipt_type: 'SALE' | 'REFUND';
  receipt_number: string;
  locale: string;
  currency: string;
  document: Record<string, unknown>;
  generated_at: IsoDateTime;
}

export interface FulfillmentTicket {
  id: UUID;
  order_id: UUID;
  station_id: UUID;
  source_ticket_id: UUID | null;
  generation_number: number;
  display_number: string;
  status: FulfillmentStatus;
  priority: number;
  failure_reason_code: FulfillmentFailureReason | null;
  failure_detail: string | null;
  acknowledged_at: IsoDateTime | null;
  started_at: IsoDateTime | null;
  ready_at: IsoDateTime | null;
  collected_at: IsoDateTime | null;
  version: number;
  items: Array<{
    order_item_id: UUID;
    quantity: number;
    name: string;
    preparation_snapshot: Record<string, unknown>;
    allergen_snapshot: Record<string, unknown>;
  }>;
}

export interface ManualReview {
  id: UUID;
  store_id: UUID;
  order_id: UUID;
  fulfillment_ticket_id: UUID | null;
  case_number: string;
  status: ReviewStatus;
  reason_code: FulfillmentFailureReason;
  priority: number;
  assigned_to: UUID | null;
  resolution_code: ReviewResolution | null;
  assigned_at: IsoDateTime | null;
  resolved_at: IsoDateTime | null;
  closed_at: IsoDateTime | null;
  version: number;
}

export interface RefundResponse {
  id: UUID;
  order_id: UUID;
  payment_attempt_id: UUID;
  amount_minor: number;
  currency: string;
  reason_code: string;
  status: RefundStatus;
  psp_reference: string | null;
  failure_code: string | null;
  completed_at: IsoDateTime | null;
  version: number;
}

export interface OperationsSummary {
  store_id: UUID;
  open_orders: number;
  open_tickets: number;
  open_manual_reviews: number;
  unknown_payments: number;
  paid_orders_without_tickets: number;
  pending_outbox_events: number;
}

export interface AuditLog {
  id: UUID;
  tenant_id: UUID;
  store_id: UUID | null;
  actor_type: 'USER' | 'KIOSK' | 'SYSTEM' | 'PROVIDER';
  actor_user_id: UUID | null;
  actor_device_id: UUID | null;
  action: string;
  target_type: string;
  target_id: UUID;
  correlation_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  occurred_at: IsoDateTime;
}

export function formatMinorUnits(amountMinor: number, currency = 'EUR', locale = 'nl-NL') {
  return new Intl.NumberFormat(locale, { style: 'currency', currency }).format(amountMinor / 100);
}
