import { describe, expect, it, vi } from 'vitest';
import { ApiError, createApiClient } from './index';

describe('API client', () => {
  it('adds kiosk credentials and idempotency headers without putting secrets in the URL', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ id: 'order-1', payment_attempts: [] }), {
        status: 201,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const client = createApiClient({ baseUrl: 'http://127.0.0.1:8000/api/v1/', fetch: fetcher });
    await client.kiosk.createOrder(
      { id: 'device-id', key: 'device-secret' },
      'quote-id',
      'CARD',
      'idem-1',
    );

    const [url, init] = fetcher.mock.calls[0] ?? [];
    expect(url).toBe('http://127.0.0.1:8000/api/v1/kiosk/orders');
    const headers = new Headers(init?.headers);
    expect(headers.get('X-Kiosk-Key')).toBe('device-secret');
    expect(headers.get('Idempotency-Key')).toBe('idem-1');
    expect(url).toBeDefined();
    const requestUrl =
      typeof url === 'string' ? url : url instanceof URL ? url.href : (url?.url ?? '');
    expect(requestUrl).not.toContain('device-secret');
  });

  it('surfaces problem responses as ApiError', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ title: 'Conflict', detail: 'Version changed' }), {
        status: 409,
        headers: { 'Content-Type': 'application/problem+json' },
      }),
    );
    const client = createApiClient({ baseUrl: 'https://example.test/api/v1', fetch: fetcher });
    try {
      await client.admin.orders('token');
      throw new Error('Expected the request to fail');
    } catch (error) {
      expect(error).toBeInstanceOf(ApiError);
      expect(error).toMatchObject({ status: 409, message: 'Version changed' });
    }
  });
});
