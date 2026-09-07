import type { ProblemDetails } from './types';

const DEFAULT_API_URL = 'http://127.0.0.1:8000/api/v1';

export const configuredDefaultApiUrl = normalizeApiBaseUrl(
  typeof import.meta.env.VITE_API_URL === 'string' ? import.meta.env.VITE_API_URL : DEFAULT_API_URL,
);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly correlationId: string | null;
  readonly details: Record<string, unknown>;

  constructor(
    message: string,
    options: {
      status: number;
      code?: string;
      correlationId?: string | null;
      details?: Record<string, unknown>;
    },
  ) {
    super(message);
    this.name = 'ApiError';
    this.status = options.status;
    this.code = options.code ?? 'http_error';
    this.correlationId = options.correlationId ?? null;
    this.details = options.details ?? {};
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE';
  body?: unknown;
  headers?: Record<string, string>;
  authenticated?: boolean;
}

export interface ApiClient {
  request<T>(path: string, options?: RequestOptions): Promise<T>;
  get<T>(path: string): Promise<T>;
  post<T>(path: string, body?: unknown, headers?: Record<string, string>): Promise<T>;
  patch<T>(path: string, body: unknown): Promise<T>;
}

export function normalizeApiBaseUrl(value: string): string {
  const normalized = value.trim().replace(/\/+$/, '');
  if (!normalized) {
    throw new Error('API URL is required.');
  }
  if (normalized.startsWith('/')) {
    return normalized;
  }
  let parsed: URL;
  try {
    parsed = new URL(normalized);
  } catch {
    throw new Error('API URL must be an absolute HTTP(S) URL or an application-relative path.');
  }
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('API URL must use HTTP or HTTPS.');
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('API URL cannot contain credentials, query parameters, or a fragment.');
  }
  const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(parsed.hostname);
  if (parsed.protocol === 'http:' && !loopback) {
    throw new Error('Remote API URLs must use HTTPS. HTTP is only allowed for loopback.');
  }
  return parsed.toString().replace(/\/$/, '');
}

function createCorrelationId(): string {
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return globalThis.crypto.randomUUID();
  }
  return `admin-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function createIdempotencyKey(prefix = 'admin'): string {
  return `${prefix}-${createCorrelationId()}`;
}

async function readProblem(response: Response): Promise<ProblemDetails> {
  const contentType = response.headers.get('content-type') ?? '';
  if (!contentType.includes('json')) {
    return { detail: response.statusText || 'The request failed.' };
  }
  try {
    return (await response.json()) as ProblemDetails;
  } catch {
    return { detail: 'The server returned an unreadable error response.' };
  }
}

export function createApiClient(options: {
  apiBaseUrl: string;
  getAccessToken: () => string | null;
  onUnauthorized: (error: ApiError) => void;
  refresh?: () => Promise<string | null>;
}): ApiClient {
  const apiBaseUrl = normalizeApiBaseUrl(options.apiBaseUrl);

  const attempt = async (
    path: string,
    requestOptions: RequestOptions,
    token: string | null,
    authenticated: boolean,
  ): Promise<Response> => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 30_000);
    const headers = new Headers({
      Accept: 'application/json',
      'X-Correlation-ID': createCorrelationId(),
      ...requestOptions.headers,
    });
    if (requestOptions.body !== undefined) {
      headers.set('Content-Type', 'application/json');
    }
    if (authenticated && token) {
      headers.set('Authorization', `Bearer ${token}`);
    }
    try {
      const baseUrl = new URL(`${apiBaseUrl}/`, window.location.origin);
      const relativePath = path.replace(/^\/+/, '');
      const requestUrl = new URL(relativePath, baseUrl);
      if (
        requestUrl.origin !== baseUrl.origin ||
        !requestUrl.pathname.startsWith(baseUrl.pathname) ||
        relativePath.startsWith('..')
      ) {
        throw new ApiError('The requested API path is outside the configured API base URL.', {
          status: 0,
          code: 'invalid_request_path',
        });
      }
      return await fetch(requestUrl, {
        method: requestOptions.method ?? 'GET',
        headers,
        body: requestOptions.body === undefined ? undefined : JSON.stringify(requestOptions.body),
        signal: controller.signal,
        cache: 'no-store',
        credentials: 'omit',
        referrerPolicy: 'no-referrer',
      });
    } catch (error) {
      if (error instanceof ApiError) throw error;
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new ApiError('The API did not respond within 30 seconds.', {
          status: 0,
          code: 'request_timeout',
        });
      }
      throw new ApiError(
        error instanceof Error ? `Cannot reach the API: ${error.message}` : 'Cannot reach the API.',
        { status: 0, code: 'network_error' },
      );
    } finally {
      window.clearTimeout(timeout);
    }
  };

  const request = async <T>(path: string, requestOptions: RequestOptions = {}): Promise<T> => {
    const authenticated = requestOptions.authenticated ?? true;
    let response = await attempt(path, requestOptions, options.getAccessToken(), authenticated);

    // On a 401 for an authenticated call, silently refresh the access token once
    // and retry the request (see the periodic refresh for the proactive path).
    if (response.status === 401 && authenticated && options.refresh) {
      const newToken = await options.refresh();
      if (newToken) {
        response = await attempt(path, requestOptions, newToken, authenticated);
      }
    }

    if (!response.ok) {
      const problem = await readProblem(response);
      const error = new ApiError(
        problem.detail ??
          (response.status === 401
            ? 'The username, password, or tenant code is incorrect.'
            : `Request failed with status ${response.status}.`),
        {
          status: response.status,
          code: problem.title ?? 'http_error',
          correlationId: problem.correlation_id ?? response.headers.get('x-correlation-id') ?? null,
          details: problem.details,
        },
      );
      if (response.status === 401 && authenticated) {
        options.onUnauthorized(error);
      }
      throw error;
    }

    if (response.status === 204) {
      return undefined as T;
    }
    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('json')) {
      return undefined as T;
    }
    return (await response.json()) as T;
  };

  return {
    request,
    get: <T>(path: string) => request<T>(path),
    post: <T>(path: string, body?: unknown, headers?: Record<string, string>) =>
      request<T>(path, { method: 'POST', body, headers }),
    patch: <T>(path: string, body: unknown) => request<T>(path, { method: 'PATCH', body }),
  };
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const correlation = error.correlationId ? ` Reference: ${error.correlationId}.` : '';
    const fieldErrors = Array.isArray(error.details.errors)
      ? error.details.errors
          .map((entry) => {
            if (!entry || typeof entry !== 'object') return null;
            const candidate = entry as { location?: unknown; message?: unknown };
            const location = Array.isArray(candidate.location)
              ? candidate.location.filter((value): value is string => typeof value === 'string')
              : [];
            const message = typeof candidate.message === 'string' ? candidate.message : null;
            if (!message) return null;
            const field = location
              .filter((value) => !['body', 'query', 'path'].includes(value))
              .join('.');
            return field ? `${field}: ${message}` : message;
          })
          .filter((value): value is string => value !== null)
      : [];
    const validation = fieldErrors.length > 0 ? ` ${fieldErrors.join('; ')}.` : '';
    return `${error.message}${validation}${correlation}`;
  }
  return error instanceof Error ? error.message : 'An unexpected error occurred.';
}
