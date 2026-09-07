import type {
  FulfillmentType,
  KioskOrder,
  KioskHeartbeat,
  KioskReceipt,
  KioskStoreStatus,
  PaymentMethod,
  Quote,
  QuoteItemRequest,
  StoreCatalog,
} from './types';

export interface KioskApi {
  getStoreStatus: () => Promise<KioskStoreStatus>;
  heartbeat: () => Promise<KioskHeartbeat>;
  getCatalog: (locale: string) => Promise<StoreCatalog>;
  createQuote: (
    locale: string,
    items: QuoteItemRequest[],
    fulfillmentType: FulfillmentType,
  ) => Promise<Quote>;
  createOrder: (
    quoteId: string,
    paymentMethod: PaymentMethod,
    idempotencyKey: string,
  ) => Promise<KioskOrder>;
  getOrder: (orderId: string) => Promise<KioskOrder>;
  retryPayment: (
    orderId: string,
    paymentMethod: PaymentMethod,
    idempotencyKey: string,
  ) => Promise<KioskOrder>;
  executePayment: (attemptId: string) => Promise<KioskOrder>;
  reconcilePayment: (attemptId: string) => Promise<KioskOrder>;
  getReceipts: (orderId: string) => Promise<KioskReceipt[]>;
}

export interface KioskRuntimeConfig {
  apiBaseUrl: string;
  kioskId: string;
  kioskKey: string;
}

interface ProblemDetails {
  type?: unknown;
  title?: unknown;
  status?: unknown;
  detail?: unknown;
  correlation_id?: unknown;
}

const SESSION_CONFIG_KEY = 'smart-drink:kiosk-session-config';
const FALLBACK_API_BASE_URL = 'http://127.0.0.1:8000/api/v1';
export const DEFAULT_API_BASE_URL = normalizeKioskApiBaseUrl(
  typeof import.meta.env.VITE_API_BASE_URL === 'string'
    ? import.meta.env.VITE_API_BASE_URL
    : FALLBACK_API_BASE_URL,
);

export class ApiError extends Error {
  readonly code: string;
  readonly status: number | null;
  readonly correlationId: string | null;

  constructor(
    message: string,
    options: { code: string; status?: number | null; correlationId?: string | null },
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = options.code;
    this.status = options.status ?? null;
    this.correlationId = options.correlationId ?? null;
  }
}

export function normalizeKioskApiBaseUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) throw new Error('API-adres is verplicht.');
  // Same-origin deployments (one reverse proxy in front of the API and the
  // three web apps) configure a relative path such as `/api/v1`.
  if (trimmed.startsWith('/')) {
    return trimmed.replace(/\/+$/, '');
  }
  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error('Voer een geldig HTTP- of HTTPS-adres in.');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('Het API-adres moet HTTP of HTTPS gebruiken.');
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('Het API-adres mag geen inloggegevens, query of fragment bevatten.');
  }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname);
  if (parsed.protocol === 'http:' && !loopback) {
    throw new Error('Een extern API-adres moet HTTPS gebruiken. HTTP mag alleen lokaal.');
  }
  return parsed.toString().replace(/\/$/, '');
}

function makeCorrelationId(): string {
  if (typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `kiosk-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function textValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

async function parseProblem(response: Response): Promise<ApiError> {
  let problem: ProblemDetails = {};
  try {
    problem = (await response.json()) as ProblemDetails;
  } catch {
    // An upstream proxy can return an empty or non-JSON error page.
  }

  const type = textValue(problem.type);
  const code =
    textValue(problem.title) ??
    (type?.startsWith('urn:smart-drink:error:')
      ? type.slice('urn:smart-drink:error:'.length)
      : null) ??
    `http_${response.status}`;
  const message = textValue(problem.detail) ?? `Request failed with status ${response.status}.`;
  return new ApiError(message, {
    code,
    status: response.status,
    correlationId: textValue(problem.correlation_id) ?? response.headers.get('X-Correlation-ID'),
  });
}

export class KioskApiClient implements KioskApi {
  private readonly apiBaseUrl: string;
  private readonly kioskId: string;
  private readonly kioskKey: string;

  constructor(config: KioskRuntimeConfig) {
    this.apiBaseUrl = normalizeKioskApiBaseUrl(config.apiBaseUrl);
    this.kioskId = config.kioskId.trim();
    this.kioskKey = config.kioskKey.trim();
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30_000);
    const headers = new Headers(init.headers);
    headers.set('Accept', 'application/json');
    headers.set('X-Kiosk-ID', this.kioskId);
    headers.set('X-Kiosk-Key', this.kioskKey);
    headers.set('X-Correlation-ID', makeCorrelationId());
    if (init.body !== undefined) {
      headers.set('Content-Type', 'application/json');
    }

    try {
      const response = await fetch(`${this.apiBaseUrl}${path}`, {
        ...init,
        headers,
        signal: controller.signal,
        cache: 'no-store',
      });
      if (!response.ok) {
        throw await parseProblem(response);
      }
      return (await response.json()) as T;
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ApiError('The Edge API did not respond in time.', {
          code: 'request_timeout',
        });
      }
      throw new ApiError('The kiosk could not reach the Edge API.', {
        code: 'network_unavailable',
      });
    } finally {
      window.clearTimeout(timeout);
    }
  }

  getCatalog(locale: string): Promise<StoreCatalog> {
    return this.request(`/kiosk/catalog?locale=${encodeURIComponent(locale)}`);
  }

  getStoreStatus(): Promise<KioskStoreStatus> {
    return this.request('/kiosk/store-status');
  }

  heartbeat(): Promise<KioskHeartbeat> {
    return this.request('/kiosk/heartbeat', { method: 'POST' });
  }

  createQuote(locale: string, items: QuoteItemRequest[], fulfillmentType: FulfillmentType): Promise<Quote> {
    return this.request('/kiosk/quotes', {
      method: 'POST',
      body: JSON.stringify({ locale, items, fulfillment_type: fulfillmentType }),
    });
  }

  createOrder(
    quoteId: string,
    paymentMethod: PaymentMethod,
    idempotencyKey: string,
  ): Promise<KioskOrder> {
    return this.request('/kiosk/orders', {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ quote_id: quoteId, payment_method: paymentMethod }),
    });
  }

  getOrder(orderId: string): Promise<KioskOrder> {
    return this.request(`/kiosk/orders/${encodeURIComponent(orderId)}`);
  }

  retryPayment(
    orderId: string,
    paymentMethod: PaymentMethod,
    idempotencyKey: string,
  ): Promise<KioskOrder> {
    return this.request(`/kiosk/orders/${encodeURIComponent(orderId)}/payment-attempts`, {
      method: 'POST',
      headers: { 'Idempotency-Key': idempotencyKey },
      body: JSON.stringify({ payment_method: paymentMethod }),
    });
  }

  executePayment(attemptId: string): Promise<KioskOrder> {
    return this.request(`/kiosk/payment-attempts/${encodeURIComponent(attemptId)}/execute`, {
      method: 'POST',
    });
  }

  reconcilePayment(attemptId: string): Promise<KioskOrder> {
    return this.request(`/kiosk/payment-attempts/${encodeURIComponent(attemptId)}/reconcile`, {
      method: 'POST',
    });
  }

  getReceipts(orderId: string): Promise<KioskReceipt[]> {
    return this.request(`/kiosk/orders/${encodeURIComponent(orderId)}/receipts`);
  }
}

function validConfig(value: unknown): value is KioskRuntimeConfig {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const candidate = value as Partial<KioskRuntimeConfig>;
  return Boolean(
    candidate.apiBaseUrl?.trim() && candidate.kioskId?.trim() && candidate.kioskKey?.trim(),
  );
}

export function readKioskRuntimeConfig(): KioskRuntimeConfig | null {
  try {
    const stored = window.sessionStorage.getItem(SESSION_CONFIG_KEY);
    if (!stored) {
      return null;
    }
    const parsed: unknown = JSON.parse(stored);
    if (validConfig(parsed)) {
      return { ...parsed, apiBaseUrl: normalizeKioskApiBaseUrl(parsed.apiBaseUrl) };
    }
    clearSessionKioskConfig();
    return null;
  } catch {
    clearSessionKioskConfig();
    return null;
  }
}

export function saveSessionKioskConfig(config: KioskRuntimeConfig): void {
  window.sessionStorage.setItem(
    SESSION_CONFIG_KEY,
    JSON.stringify({ ...config, apiBaseUrl: normalizeKioskApiBaseUrl(config.apiBaseUrl) }),
  );
}

export function clearSessionKioskConfig(): void {
  window.sessionStorage.removeItem(SESSION_CONFIG_KEY);
}

export function createConfiguredKioskApi(): KioskApi | null {
  const config = readKioskRuntimeConfig();
  return config ? new KioskApiClient(config) : null;
}
