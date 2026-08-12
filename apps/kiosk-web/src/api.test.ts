import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  DEFAULT_API_BASE_URL,
  ApiError,
  clearSessionKioskConfig,
  KioskApiClient,
  normalizeKioskApiBaseUrl,
  readKioskRuntimeConfig,
  saveSessionKioskConfig,
} from './api';

describe('KioskApiClient', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    clearSessionKioskConfig();
  });

  it('uses the loopback API URL when no build-time demo override is configured', () => {
    expect(DEFAULT_API_BASE_URL).toBe('http://127.0.0.1:8000/api/v1');
  });

  it('adds both device credentials, correlation ID, and idempotency key', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'order-1' }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const client = new KioskApiClient({
      apiBaseUrl: 'http://127.0.0.1:8000/api/v1/',
      kioskId: 'kiosk-id',
      kioskKey: 'kiosk-secret',
    });

    await client.createOrder('quote-1', 'CONTACTLESS', 'stable-key');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe('http://127.0.0.1:8000/api/v1/kiosk/orders');
    expect(headers.get('X-Kiosk-ID')).toBe('kiosk-id');
    expect(headers.get('X-Kiosk-Key')).toBe('kiosk-secret');
    expect(headers.get('X-Correlation-ID')).toBeTruthy();
    expect(headers.get('Idempotency-Key')).toBe('stable-key');
    expect(init.cache).toBe('no-store');
  });

  it('maps RFC7807 errors and preserves the support correlation reference', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            type: 'urn:smart-drink:error:store_not_accepting_orders',
            title: 'store_not_accepting_orders',
            status: 409,
            detail: 'The store is not accepting orders',
            correlation_id: 'correlation-123',
          }),
          { status: 409, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    );
    const client = new KioskApiClient({
      apiBaseUrl: 'https://edge.example/api/v1',
      kioskId: 'kiosk-id',
      kioskKey: 'kiosk-secret',
    });

    const promise = client.createQuote('nl-NL', [
      { product_id: 'product-1', quantity: 1, option_value_ids: [] },
    ]);

    await expect(promise).rejects.toMatchObject({
      code: 'store_not_accepting_orders',
      status: 409,
      correlationId: 'correlation-123',
    } satisfies Partial<ApiError>);
  });

  it('keeps device credentials in session storage instead of persistent storage', () => {
    saveSessionKioskConfig({
      apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
      kioskId: 'kiosk-id',
      kioskKey: 'kiosk-secret',
    });

    expect(readKioskRuntimeConfig()).toEqual({
      apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
      kioskId: 'kiosk-id',
      kioskKey: 'kiosk-secret',
    });
    expect(window.localStorage.length).toBe(0);
  });

  it('requires HTTPS for non-loopback API addresses', () => {
    expect(() => normalizeKioskApiBaseUrl('http://edge.example/api/v1')).toThrow(/HTTPS/);
    expect(normalizeKioskApiBaseUrl('http://127.0.0.1:8000/api/v1/')).toBe(
      'http://127.0.0.1:8000/api/v1',
    );
  });

  it('calls the kiosk status and heartbeat endpoints with the device credentials', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ store_id: 'store-1', accepting_orders: true }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ resource_id: 'kiosk-id', server_time: 'now' }), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      );
    vi.stubGlobal('fetch', fetchMock);
    const client = new KioskApiClient({
      apiBaseUrl: 'https://edge.example/api/v1',
      kioskId: 'kiosk-id',
      kioskKey: 'kiosk-secret',
    });

    await client.getStoreStatus();
    await client.heartbeat();

    expect(fetchMock.mock.calls[0]?.[0]).toBe('https://edge.example/api/v1/kiosk/store-status');
    expect(fetchMock.mock.calls[1]?.[0]).toBe('https://edge.example/api/v1/kiosk/heartbeat');
    expect((fetchMock.mock.calls[1]?.[1] as RequestInit).method).toBe('POST');
  });
});
