import type {
  AccessTokenResponse,
  AuditLog,
  FulfillmentFailureReason,
  FulfillmentStatus,
  FulfillmentTicket,
  KioskOrderResponse,
  KioskReceiptResponse,
  ManualReview,
  OperationsSummary,
  OrderResponse,
  PaymentMethod,
  PrincipalResponse,
  ProblemDetails,
  QuoteRequest,
  QuoteResponse,
  RefundResponse,
  ReviewResolution,
  StoreCatalog,
  StorePolicyResponse,
  StoreWithPolicyResponse,
  UUID,
} from '@smart-drink/contracts';

export type DeviceCredentials = { id: string; key: string };
export type RequestAuth =
  | { kind: 'none' }
  | { kind: 'staff'; token: string }
  | { kind: 'kiosk'; credentials: DeviceCredentials }
  | { kind: 'fulfillment'; credentials: DeviceCredentials; token: string };

export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemDetails | null;

  constructor(status: number, problem: ProblemDetails | null) {
    super(problem?.detail ?? problem?.title ?? `Request failed with status ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.problem = problem;
  }
}

export interface ApiClientOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
}

type RequestOptions = Omit<RequestInit, 'body' | 'headers'> & {
  auth?: RequestAuth;
  body?: unknown;
  headers?: HeadersInit;
  idempotencyKey?: string;
};

function normalizedBaseUrl(value: string) {
  const trimmed = value.trim().replace(/\/+$/, '');
  if (!/^https?:\/\//u.test(trimmed)) {
    throw new Error('API base URL must use http:// or https://');
  }
  return trimmed;
}

export function createApiClient(options: ApiClientOptions) {
  const baseUrl = normalizedBaseUrl(options.baseUrl);
  const fetcher = options.fetch ?? globalThis.fetch;
  if (!fetcher) throw new Error('Fetch is not available in this runtime');

  async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const headers = new Headers(options.headers);
    headers.set('Accept', 'application/json');
    if (options.body !== undefined) headers.set('Content-Type', 'application/json');
    if (options.idempotencyKey) headers.set('Idempotency-Key', options.idempotencyKey);
    const auth = options.auth ?? { kind: 'none' };
    if (auth.kind === 'staff' || (auth.kind === 'fulfillment' && auth.token)) {
      headers.set('Authorization', `Bearer ${auth.token}`);
    }
    if (auth.kind === 'kiosk') {
      headers.set('X-Kiosk-ID', auth.credentials.id);
      headers.set('X-Kiosk-Key', auth.credentials.key);
    }
    if (auth.kind === 'fulfillment') {
      headers.set('X-Endpoint-ID', auth.credentials.id);
      headers.set('X-Endpoint-Key', auth.credentials.key);
    }

    const response = await fetcher(`${baseUrl}${path}`, {
      ...options,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
    if (response.status === 204) return undefined as T;
    const contentType = response.headers.get('content-type') ?? '';
    const value: unknown = contentType.includes('json') ? await response.json() : null;
    if (!response.ok) throw new ApiError(response.status, (value as ProblemDetails | null) ?? null);
    return value as T;
  }

  const query = (values: Record<string, string | number | undefined>) => {
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (value !== undefined) params.set(key, String(value));
    });
    const encoded = params.toString();
    return encoded ? `?${encoded}` : '';
  };

  return {
    request,
    auth: {
      login: (tenantCode: string, username: string, password: string) =>
        request<AccessTokenResponse>('/auth/token', {
          method: 'POST',
          body: { tenant_code: tenantCode, username, password },
        }),
      me: (token: string) =>
        request<PrincipalResponse>('/auth/me', { auth: { kind: 'staff', token } }),
    },
    kiosk: {
      heartbeat: (credentials: DeviceCredentials) =>
        request<{ resource_id: UUID; server_time: string }>('/kiosk/heartbeat', {
          method: 'POST',
          auth: { kind: 'kiosk', credentials },
        }),
      storeStatus: (credentials: DeviceCredentials) =>
        request<{ store_id: UUID; accepting_orders: boolean; currency: string; locale: string }>(
          '/kiosk/store-status',
          { auth: { kind: 'kiosk', credentials } },
        ),
      catalog: (credentials: DeviceCredentials, locale = 'nl-NL') =>
        request<StoreCatalog>(`/kiosk/catalog${query({ locale })}`, {
          auth: { kind: 'kiosk', credentials },
        }),
      quote: (credentials: DeviceCredentials, body: QuoteRequest) =>
        request<QuoteResponse>('/kiosk/quotes', {
          method: 'POST',
          auth: { kind: 'kiosk', credentials },
          body,
        }),
      createOrder: (
        credentials: DeviceCredentials,
        quoteId: UUID,
        paymentMethod: PaymentMethod,
        idempotencyKey: string,
      ) =>
        request<KioskOrderResponse>('/kiosk/orders', {
          method: 'POST',
          auth: { kind: 'kiosk', credentials },
          body: { quote_id: quoteId, payment_method: paymentMethod },
          idempotencyKey,
        }),
      getOrder: (credentials: DeviceCredentials, orderId: UUID) =>
        request<KioskOrderResponse>(`/kiosk/orders/${orderId}`, {
          auth: { kind: 'kiosk', credentials },
        }),
      executePayment: (credentials: DeviceCredentials, attemptId: UUID) =>
        request<KioskOrderResponse>(`/kiosk/payment-attempts/${attemptId}/execute`, {
          method: 'POST',
          auth: { kind: 'kiosk', credentials },
        }),
      reconcilePayment: (credentials: DeviceCredentials, attemptId: UUID) =>
        request<KioskOrderResponse>(`/kiosk/payment-attempts/${attemptId}/reconcile`, {
          method: 'POST',
          auth: { kind: 'kiosk', credentials },
        }),
      receipts: (credentials: DeviceCredentials, orderId: UUID) =>
        request<KioskReceiptResponse[]>(`/kiosk/orders/${orderId}/receipts`, {
          auth: { kind: 'kiosk', credentials },
        }),
    },
    fulfillment: {
      heartbeat: (credentials: DeviceCredentials) =>
        request<{ endpoint_id: UUID; station_id: UUID; heartbeat_at: string; version: number }>(
          '/fulfillment/heartbeat',
          { method: 'POST', auth: { kind: 'fulfillment', credentials, token: '' } },
        ),
      tickets: (credentials: DeviceCredentials, token: string) =>
        request<FulfillmentTicket[]>('/fulfillment/tickets', {
          auth: { kind: 'fulfillment', credentials, token },
        }),
      transition: (
        credentials: DeviceCredentials,
        token: string,
        ticketId: UUID,
        expectedVersion: number,
        toStatus: FulfillmentStatus,
        failure?: { reason: FulfillmentFailureReason; detail?: string },
      ) =>
        request<FulfillmentTicket>(`/fulfillment/tickets/${ticketId}/transition`, {
          method: 'POST',
          auth: { kind: 'fulfillment', credentials, token },
          body: {
            to_status: toStatus,
            expected_version: expectedVersion,
            failure_reason_code: failure?.reason,
            failure_detail: failure?.detail,
          },
        }),
    },
    admin: {
      stores: (token: string) =>
        request<StoreWithPolicyResponse[]>('/admin/organization/stores', {
          auth: { kind: 'staff', token },
        }),
      updateStorePolicy: (
        token: string,
        storeId: UUID,
        body: Omit<StorePolicyResponse, 'store_id'>,
      ) =>
        request<StorePolicyResponse>(`/admin/organization/stores/${storeId}/policy`, {
          method: 'PATCH',
          auth: { kind: 'staff', token },
          body: { ...body, expected_version: body.version },
        }),
      orders: (token: string, limit = 100) =>
        request<OrderResponse[]>(`/admin/orders${query({ limit })}`, {
          auth: { kind: 'staff', token },
        }),
      reviews: (token: string, limit = 100) =>
        request<ManualReview[]>(`/admin/reviews${query({ limit })}`, {
          auth: { kind: 'staff', token },
        }),
      assignReview: (token: string, review: ManualReview, assigneeUserId?: UUID | null) =>
        request<ManualReview>(`/admin/reviews/${review.id}/assign`, {
          method: 'POST',
          auth: { kind: 'staff', token },
          body: { expected_version: review.version, assignee_user_id: assigneeUserId ?? null },
        }),
      resolveReview: (
        token: string,
        review: ManualReview,
        resolution: ReviewResolution,
        values: { refundAmountMinor?: number; notes?: string },
        idempotencyKey: string,
      ) =>
        request<ManualReview>(`/admin/reviews/${review.id}/resolve`, {
          method: 'POST',
          auth: { kind: 'staff', token },
          idempotencyKey,
          body: {
            expected_version: review.version,
            resolution,
            refund_amount_minor: values.refundAmountMinor,
            notes: values.notes ?? '',
            payload: {},
          },
        }),
      refunds: (token: string, limit = 100) =>
        request<RefundResponse[]>(`/admin/payments/refunds${query({ limit })}`, {
          auth: { kind: 'staff', token },
        }),
      executeRefund: (token: string, refundId: UUID) =>
        request<RefundResponse>(`/admin/payments/refunds/${refundId}/execute`, {
          method: 'POST',
          auth: { kind: 'staff', token },
        }),
      reconcileRefund: (token: string, refundId: UUID) =>
        request<RefundResponse>(`/admin/payments/refunds/${refundId}/reconcile`, {
          method: 'POST',
          auth: { kind: 'staff', token },
        }),
      operations: (token: string) =>
        request<OperationsSummary[]>('/admin/reports/operations', {
          auth: { kind: 'staff', token },
        }),
      audit: (token: string, limit = 100) =>
        request<AuditLog[]>(`/admin/audit${query({ limit })}`, {
          auth: { kind: 'staff', token },
        }),
    },
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

export function createIdempotencyKey(prefix = 'web') {
  const random = globalThis.crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2);
  return `${prefix}-${random}`;
}
