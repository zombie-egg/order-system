import { describe, expect, it } from 'vitest';
import { normalizeApiBaseUrl } from './api';

describe('normalizeApiBaseUrl', () => {
  it('normalizes an approved HTTP API origin and path', () => {
    expect(normalizeApiBaseUrl(' http://127.0.0.1:8000/api/v1/ ')).toBe(
      'http://127.0.0.1:8000/api/v1',
    );
  });

  it('keeps a same-origin relative base path and strips trailing slashes', () => {
    expect(normalizeApiBaseUrl(' /api/v1/ ')).toBe('/api/v1');
  });

  it('rejects credential-bearing and non-HTTP addresses', () => {
    expect(() => normalizeApiBaseUrl('file:///C:/edge-api')).toThrow(/HTTP or HTTPS/);
    expect(() => normalizeApiBaseUrl('https://staff:secret@example.test/api/v1')).toThrow(
      /must not contain credentials/,
    );
  });
});
