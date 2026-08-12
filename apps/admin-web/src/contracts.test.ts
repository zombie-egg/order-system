import { describe, expect, it } from 'vitest';
import {
  catalogItemExample,
  navigationLabelsForPermissions,
  STAFF_ROLE_CODES,
} from './admin-contracts';
import { createIdempotencyKey, normalizeApiBaseUrl } from './api';
import { createApiClient } from './api';

describe('Admin backend contract guards', () => {
  it('uses only role codes seeded by the backend', () => {
    expect(STAFF_ROLE_CODES).toEqual(['manager', 'staff', 'reviewer', 'owner']);
    expect(STAFF_ROLE_CODES).not.toContain('operator');
  });

  it('keeps catalog visible for the backend read permission', () => {
    expect(navigationLabelsForPermissions(['catalog:read'])).toContain('Catalog & pricing');
  });

  it('provides non-empty examples for resources whose API requires items', () => {
    expect(JSON.parse(catalogItemExample('option-group'))).toHaveLength(1);
    expect(JSON.parse(catalogItemExample('price-book'))).toHaveLength(1);
    expect(JSON.parse(catalogItemExample('tax-policy'))).toHaveLength(1);
  });

  it('creates stable-format idempotency keys without requiring randomUUID', () => {
    expect(createIdempotencyKey('manual-review')).toMatch(/^manual-review-/u);
  });

  it('allows loopback HTTP and rejects remote insecure API addresses', () => {
    expect(normalizeApiBaseUrl('http://127.0.0.1:8000/api/v1/')).toBe(
      'http://127.0.0.1:8000/api/v1',
    );
    expect(() => normalizeApiBaseUrl('http://edge.example.test/api/v1')).toThrow(/HTTPS/u);
  });

  it('keeps requests under the configured API prefix', async () => {
    const client = createApiClient({
      apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
      getAccessToken: () => null,
      onUnauthorized: () => undefined,
    });
    await expect(client.get('../outside')).rejects.toThrow(/outside the configured API base/u);
  });
});
