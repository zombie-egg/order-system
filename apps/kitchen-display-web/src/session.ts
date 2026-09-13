import type { KitchenApiCredentials } from './api';

const STORAGE_KEY = 'smart-drink:kds-session:v1';

export type StoredKitchenSession = KitchenApiCredentials;

function isStoredKitchenSession(value: unknown): value is StoredKitchenSession {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const candidate = value as Partial<KitchenApiCredentials>;
  return (
    typeof candidate.apiBaseUrl === 'string' &&
    typeof candidate.endpointId === 'string' &&
    typeof candidate.endpointKey === 'string'
  );
}

export function readKitchenSession(): StoredKitchenSession | null {
  const serialized = sessionStorage.getItem(STORAGE_KEY);
  if (!serialized) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(serialized);
    if (!isStoredKitchenSession(parsed)) {
      clearKitchenSession();
      return null;
    }
    return parsed;
  } catch {
    clearKitchenSession();
    return null;
  }
}

export function writeKitchenSession(session: StoredKitchenSession): void {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
}

export function clearKitchenSession(): void {
  sessionStorage.removeItem(STORAGE_KEY);
}
