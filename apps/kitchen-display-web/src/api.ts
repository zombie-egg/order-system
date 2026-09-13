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

export interface LoginRequest {
  tenant_code: string;
  username: string;
  password: string;
}

export interface AccessTokenResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
}

export interface FulfillmentHeartbeatResponse {
  endpoint_id: string;
  station_id: string;
  heartbeat_at: string;
  version: number;
}

export interface FulfillmentTicketItem {
  order_item_id: string;
  quantity: number;
  name: string;
  preparation_snapshot: Record<string, unknown>;
  allergen_snapshot: Record<string, unknown>;
  options?: string[];
}

export interface FulfillmentTicket {
  id: string;
  order_id: string;
  station_id: string;
  source_ticket_id: string | null;
  generation_number: number;
  display_number: string;
  status: FulfillmentStatus;
  priority: number;
  fulfillment_type?: 'DINE_IN' | 'TAKEAWAY';
  failure_reason_code: FulfillmentFailureReason | null;
  failure_detail: string | null;
  acknowledged_at: string | null;
  started_at: string | null;
  ready_at: string | null;
  collected_at: string | null;
  version: number;
  items: FulfillmentTicketItem[];
}

export interface KitchenApiCredentials {
  apiBaseUrl: string;
  endpointId: string;
  endpointKey: string;
}

export interface TransitionTicketRequest {
  to_status: FulfillmentStatus;
  expected_version: number;
  failure_reason_code?: FulfillmentFailureReason;
  failure_detail?: string;
}

interface ProblemDetails {
  title?: string;
  status?: number;
  detail?: string;
  correlation_id?: string;
  details?: Record<string, unknown>;
}

const DEFAULT_TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly correlationId: string | null;
  readonly details: Record<string, unknown>;

  constructor(options: {
    message: string;
    status?: number | null;
    code?: string;
    correlationId?: string | null;
    details?: Record<string, unknown>;
  }) {
    super(options.message);
    this.name = 'ApiError';
    this.status = options.status ?? null;
    this.code = options.code ?? 'request_failed';
    this.correlationId = options.correlationId ?? null;
    this.details = options.details ?? {};
  }
}

export function normalizeApiBaseUrl(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    throw new Error('API address is required.');
  }

  // Same-origin deployments (one reverse proxy in front of the API and the
  // three web apps) configure a relative path such as `/api/v1`.
  if (trimmed.startsWith('/')) {
    return trimmed.replace(/\/+$/, '');
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    throw new Error('Enter a valid HTTP or HTTPS API address.');
  }

  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    throw new Error('The API address must use HTTP or HTTPS.');
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('The API address must not contain credentials, a query, or a fragment.');
  }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname);
  if (parsed.protocol === 'http:' && !loopback) {
    throw new Error('Remote API addresses must use HTTPS. HTTP is only allowed for loopback.');
  }

  return parsed.toString().replace(/\/$/, '');
}

function createCorrelationId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `kds-${Date.now().toString(36)}`;
}

async function readProblem(response: Response): Promise<ProblemDetails> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('json')) {
    return {};
  }
  try {
    return (await response.json()) as ProblemDetails;
  } catch {
    return {};
  }
}

async function requestJson<T>(
  apiBaseUrl: string,
  path: string,
  init: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timeout = globalThis.setTimeout(() => controller.abort(), timeoutMs);
  const correlationId = createCorrelationId();

  try {
    const response = await fetch(`${apiBaseUrl}${path}`, {
      ...init,
      cache: 'no-store',
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        'X-Correlation-ID': correlationId,
        ...init.headers,
      },
    });

    if (!response.ok) {
      const problem = await readProblem(response);
      throw new ApiError({
        message: problem.detail ?? `The server returned HTTP ${response.status}.`,
        status: response.status,
        code: problem.title ?? 'request_failed',
        correlationId:
          problem.correlation_id ?? response.headers.get('x-correlation-id') ?? correlationId,
        details: problem.details,
      });
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new ApiError({
        message: 'The API did not respond before the request timed out.',
        code: 'request_timeout',
        correlationId,
      });
    }
    throw new ApiError({
      message: navigator.onLine
        ? 'The kitchen display could not reach the API.'
        : 'This device is offline.',
      code: navigator.onLine ? 'network_error' : 'offline',
      correlationId,
    });
  } finally {
    globalThis.clearTimeout(timeout);
  }
}

function deviceHeaders(credentials: Pick<KitchenApiCredentials, 'endpointId' | 'endpointKey'>) {
  return {
    'X-Endpoint-ID': credentials.endpointId,
    'X-Endpoint-Key': credentials.endpointKey,
  };
}

export function createAccessToken(
  apiBaseUrl: string,
  request: LoginRequest,
): Promise<AccessTokenResponse> {
  return requestJson<AccessTokenResponse>(apiBaseUrl, '/auth/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(request),
  });
}

export function heartbeat(
  credentials: KitchenApiCredentials,
): Promise<FulfillmentHeartbeatResponse> {
  return requestJson<FulfillmentHeartbeatResponse>(
    credentials.apiBaseUrl,
    '/fulfillment/heartbeat',
    {
      method: 'POST',
      headers: deviceHeaders(credentials),
    },
  );
}

export function listTickets(credentials: KitchenApiCredentials): Promise<FulfillmentTicket[]> {
  return requestJson<FulfillmentTicket[]>(credentials.apiBaseUrl, '/fulfillment/tickets', {
    method: 'GET',
    headers: deviceHeaders(credentials),
  });
}

export function transitionTicket(
  credentials: KitchenApiCredentials,
  ticketId: string,
  request: TransitionTicketRequest,
): Promise<FulfillmentTicket> {
  return requestJson<FulfillmentTicket>(
    credentials.apiBaseUrl,
    `/fulfillment/tickets/${encodeURIComponent(ticketId)}/transition`,
    {
      method: 'POST',
      headers: {
        ...deviceHeaders(credentials),
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request),
    },
  );
}
