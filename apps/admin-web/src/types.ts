export type UUID = string;

export interface Principal {
  user_id: UUID;
  tenant_id: UUID;
  permissions: string[];
  store_ids: UUID[];
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  refresh_token?: string;
}

export interface StoredSession {
  apiBaseUrl: string;
  accessToken: string;
  expiresAt: string;
  refreshToken: string;
}

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  correlation_id?: string;
  details?: Record<string, unknown>;
}

export interface Store {
  id: UUID;
  code: string;
  name: string;
  city?: string | null;
  country_code: string;
  currency: string;
  locale: string;
  timezone: string;
  active: boolean;
  version: number;
}

export interface StorePolicy {
  store_id: UUID;
  accepting_orders: boolean;
  max_open_tickets: number;
  kds_heartbeat_seconds: number;
  printer_fallback_enabled: boolean;
  takeaway_fee_enabled: boolean;
  takeaway_fee_minor: number;
  version: number;
}

export interface StoreWithPolicy {
  store: Store;
  policy: StorePolicy;
}

export interface StoreDeviceCredentials {
  store_id: UUID;
  kiosk_id: UUID | null;
  kiosk_code: string | null;
  kiosk_key: string | null;
  station_id: UUID | null;
  endpoint_id: UUID | null;
  endpoint_code: string | null;
  endpoint_key: string | null;
  terminal_id: UUID | null;
  terminal_provider: string | null;
}

export interface CreatedStore extends StoreWithPolicy {
  tenant_code: string;
  device_credentials: StoreDeviceCredentials;
  manager_account: StoreManager;
}

export interface StoreManager {
  user_id: UUID;
  username: string;
  display_name: string;
  active: boolean;
}

export interface StoreConnection {
  store_id: UUID;
  store_code: string;
  store_name: string;
  tenant_code: string;
  kiosk_id: UUID | null;
  kiosk_key: string | null;
  endpoint_id: UUID | null;
  endpoint_key: string | null;
  managers: StoreManager[];
}

export interface KdsBoard {
  store_id: UUID;
  station_id: UUID;
  code: string;
  name: string;
  display_title: string | null;
  enabled: boolean;
  version: number;
}

export interface UserAccount {
  id: UUID;
  tenant_id: UUID;
  username: string;
  display_name: string;
  active: boolean;
  token_version: number;
  version: number;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrderOption {
  option_value_id: UUID;
  group_name: string;
  name: string;
  price_delta_minor: number;
}

export interface OrderItem {
  id: UUID;
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
  allergen_snapshot: Record<string, unknown>;
  options: OrderOption[];
}

export interface PaymentAttempt {
  id: UUID;
  attempt_number: number;
  provider: string;
  payment_method: string;
  status: string;
  amount_minor: number;
  currency: string;
  psp_reference: string | null;
  failure_code: string | null;
  requested_at: string;
  completed_at: string | null;
  version: number;
}

export interface Order {
  id: UUID;
  store_id: UUID;
  kiosk_id: UUID;
  quote_id: UUID;
  business_date: string;
  order_number: string;
  display_number: string;
  status: string;
  payment_status: string;
  currency: string;
  locale: string;
  prices_include_tax: boolean;
  fulfillment_type: 'DINE_IN' | 'TAKEAWAY';
  packaging_fee_minor: number;
  subtotal_minor: number;
  discount_minor: number;
  net_minor: number;
  tax_minor: number;
  total_minor: number;
  paid_minor: number;
  refunded_minor: number;
  confirmed_at: string | null;
  closed_at: string | null;
  version: number;
  items: OrderItem[];
  payment_attempts: PaymentAttempt[];
}

export interface Refund {
  id: UUID;
  order_id: UUID;
  payment_attempt_id: UUID;
  amount_minor: number;
  currency: string;
  reason_code: string;
  status: string;
  psp_reference: string | null;
  failure_code: string | null;
  completed_at: string | null;
  version: number;
}

export interface ManualReview {
  id: UUID;
  store_id: UUID;
  order_id: UUID;
  fulfillment_ticket_id: UUID | null;
  case_number: string;
  status: string;
  reason_code: string;
  priority: number;
  assigned_to: UUID | null;
  resolution_code: string | null;
  assigned_at: string | null;
  resolved_at: string | null;
  closed_at: string | null;
  version: number;
}

export interface StoreOperationsSummary {
  store_id: UUID;
  open_orders: number;
  open_tickets: number;
  open_manual_reviews: number;
  unknown_payments: number;
  paid_orders_without_tickets: number;
  pending_outbox_events: number;
}

export interface SalesSummary {
  store_id: UUID;
  start_at: string;
  end_at: string;
  currency: string;
  order_count: number;
  gross_sales_minor: number;
  discount_minor: number;
  net_minor: number;
  tax_minor: number;
  paid_minor: number;
  refunded_minor: number;
  net_collected_minor: number;
}

export interface RefundSummary {
  store_id: UUID;
  start_at: string;
  end_at: string;
  currency: string;
  refund_count: number;
  requested_minor: number;
  succeeded_minor: number;
  status_counts: Record<string, number>;
  status_amounts_minor: Record<string, number>;
}

export interface FulfillmentSummary {
  store_id: UUID;
  start_at: string;
  end_at: string;
  ticket_count: number;
  status_counts: Record<string, number>;
  average_seconds_to_acknowledge: number | null;
  average_seconds_to_ready: number | null;
  average_seconds_ready_to_collect: number | null;
}

export interface ReconciliationSummary {
  store_id: UUID;
  start_at: string;
  end_at: string;
  run_count: number;
  completed_run_count: number;
  failed_run_count: number;
  open_issue_count: number;
  critical_open_issue_count: number;
  latest_run_status: string | null;
  latest_run_started_at: string | null;
  latest_run_completed_at: string | null;
}

export interface AuditLog {
  id: UUID;
  tenant_id: UUID;
  store_id: UUID | null;
  actor_type: string;
  actor_user_id: UUID | null;
  actor_device_id: UUID | null;
  action: string;
  target_type: string;
  target_id: UUID;
  correlation_id: string | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  occurred_at: string;
}

export interface ResourceCreated {
  id: UUID;
}

export interface AdminCategory {
  id: UUID;
  code: string;
  name: string;
  sort_order: number;
  active: boolean;
}

export interface AdminProduct {
  id: UUID;
  sku: string;
  name: string;
  description: string;
  image_url: string | null;
  category_id: UUID | null;
  category_name: string | null;
  price_minor: number | null;
  currency: string | null;
  tax_category_code: string;
  status: string;
  active: boolean;
  sort_order: number;
  available: boolean;
  version: number;
  option_rules: ProductOptionRule[];
  option_prices: Record<UUID, number>;
}

export interface ProductOptionRule {
  option_group_id: UUID;
  minimum_selections: number;
  maximum_selections: number;
  sort_order: number;
  default_option_value_id: UUID | null;
}

export interface AdminOptionValue {
  id: UUID;
  code: string;
  translations: Record<string, string>;
  sort_order: number;
  active: boolean;
}

export interface AdminOptionGroup {
  id: UUID;
  store_id: UUID;
  code: string;
  translations: Record<string, string>;
  sort_order: number;
  active: boolean;
  values: AdminOptionValue[];
}

export interface AdminProductList {
  store_id: UUID;
  currency: string;
  price_book_id: UUID | null;
  products: AdminProduct[];
}

export interface ProductImageUpload {
  image_url: string;
}

export interface Branding {
  merchant_name: string;
  logo_url: string | null;
}

export interface ReportsBundle {
  sales: SalesSummary;
  refunds: RefundSummary;
  fulfillment: FulfillmentSummary;
  reconciliation: ReconciliationSummary;
}

export interface TopProductItem {
  product_id: UUID;
  sku: string;
  name: string;
  quantity: number;
  revenue_minor: number;
  currency: string;
}

export interface TopProductsResponse {
  store_ids: UUID[];
  start_at: string;
  end_at: string;
  order_by: 'quantity' | 'revenue';
  limit: number;
  currency: string;
  items: TopProductItem[];
}

export interface StoreSalesSnapshot {
  store_id: UUID | null;
  store_code: string | null;
  store_name: string | null;
  order_count: number;
  gross_sales_minor: number;
  discount_minor: number;
  net_sales_minor: number;
  tax_minor: number;
  refunded_minor: number;
  net_collected_minor: number;
  ticket_count: number;
}

export interface TrendBucket {
  bucket: string;
  order_count: number;
  gross_sales_minor: number;
  refunded_minor: number;
  ticket_count: number;
}

export interface MultiStoreSummary {
  store_id: UUID | null;
  start_at: string;
  end_at: string;
  period: 'day' | 'week' | 'month';
  currency: string;
  stores: StoreSalesSnapshot[];
  totals: StoreSalesSnapshot;
  trend: TrendBucket[];
}

export interface DashboardKpiStore {
  store_id: UUID | null;
  store_code: string | null;
  store_name: string | null;
  today_order_count: number;
  today_revenue_minor: number;
  open_tickets: number;
  open_manual_reviews: number;
  unknown_payments: number;
}

export interface DashboardKpi {
  business_date: string;
  currency: string;
  stores: DashboardKpiStore[];
  totals: DashboardKpiStore;
}
