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

export interface CatalogOptionValue {
  id: string;
  code: string;
  name: string;
  price_delta_minor: number;
}

export interface CatalogOptionGroup {
  id: string;
  code: string;
  name: string;
  minimum_selections: number;
  maximum_selections: number;
  values: CatalogOptionValue[];
}

export interface CatalogProduct {
  id: string;
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

export interface CatalogCategory {
  id: string;
  code: string;
  name: string;
  products: CatalogProduct[];
}

export interface StoreCatalog {
  store_id: string;
  locale: string;
  currency: string;
  price_book_id: string;
  categories: CatalogCategory[];
}

export interface KioskStoreStatus {
  store_id: string;
  accepting_orders: boolean;
  currency: string;
  locale: string;
}

export interface KioskHeartbeat {
  resource_id: string;
  server_time: string;
}

export interface QuoteItemRequest {
  product_id: string;
  quantity: number;
  option_value_ids: string[];
}

export interface QuoteOption {
  option_value_id: string;
  group_name: string;
  name: string;
  price_delta_minor: number;
}

export interface QuoteItem {
  line_number: number;
  product_id: string;
  sku: string;
  name: string;
  quantity: number;
  unit_price_minor: number;
  option_total_minor: number;
  discount_minor: number;
  net_minor: number;
  tax_minor: number;
  line_total_minor: number;
  options: QuoteOption[];
  allergen_snapshot: Record<string, unknown>;
}

export interface QuoteTaxLine {
  tax_category_code: string;
  tax_rate_ppm: number;
  taxable_minor: number;
  tax_minor: number;
}

export interface Quote {
  id: string;
  status: 'ACTIVE' | 'CONSUMED' | 'EXPIRED' | 'CANCELLED';
  store_id: string;
  kiosk_id: string;
  currency: string;
  locale: string;
  prices_include_tax: boolean;
  subtotal_minor: number;
  discount_minor: number;
  net_minor: number;
  tax_minor: number;
  total_minor: number;
  expires_at: string;
  items: QuoteItem[];
  tax_lines: QuoteTaxLine[];
}

export interface KioskPaymentAttempt {
  id: string;
  payment_method: PaymentMethod;
  status: PaymentStatus;
  amount_minor: number;
  currency: string;
}

export interface KioskOrderOption {
  group_name: string;
  name: string;
  price_delta_minor: number;
}

export interface KioskOrderItem {
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
  options: KioskOrderOption[];
}

export interface KioskOrder {
  id: string;
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
  items: KioskOrderItem[];
  payment_attempts: KioskPaymentAttempt[];
}

export interface KioskReceipt {
  receipt_type: 'SALE' | 'REFUND';
  receipt_number: string;
  locale: string;
  currency: string;
  document: Record<string, unknown>;
  generated_at: string;
}

export interface CartLine {
  key: string;
  product: CatalogProduct;
  optionValueIds: string[];
  selectedOptions: Array<{
    groupName: string;
    value: CatalogOptionValue;
  }>;
  quantity: number;
}
