export function formatMoneyMinor(amountMinor: number, currency = 'EUR', locale = 'nl-NL'): string {
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency,
      currencyDisplay: 'symbol',
    }).format(amountMinor / 100);
  } catch {
    return `${currency} ${(amountMinor / 100).toFixed(2)}`;
  }
}

export function formatDateTime(value: string | null | undefined, locale = 'nl-NL'): string {
  if (!value) {
    return '—';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(date);
}

export function formatDuration(seconds: number | null): string {
  if (seconds === null) {
    return '—';
  }
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return remainingSeconds === 0 ? `${minutes}m` : `${minutes}m ${remainingSeconds}s`;
}

export function formatPercentPpm(valuePpm: number): string {
  const percentage = valuePpm / 10_000;
  return `${new Intl.NumberFormat('nl-NL', { maximumFractionDigits: 2 }).format(percentage)}%`;
}

export function shortId(value: string, visible = 8): string {
  return value.length <= visible ? value : `${value.slice(0, visible)}…`;
}

export function toLocalDateTimeInput(date: Date): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function localInputToIso(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error('Enter a valid date and time.');
  }
  return date.toISOString();
}

export function parseMajorMoney(value: string): number {
  const normalized = value.trim().replace(',', '.');
  if (!/^-?\d+(?:\.\d{1,2})?$/.test(normalized)) {
    throw new Error('Money values may contain at most two decimal places.');
  }
  const minor = Math.round(Number(normalized) * 100);
  if (!Number.isSafeInteger(minor)) {
    throw new Error('Money value is outside the supported range.');
  }
  return minor;
}

export function parseJsonObject(value: string, fieldName: string): Record<string, unknown> {
  const normalized = value.trim();
  if (!normalized) {
    return {};
  }
  const parsed: unknown = JSON.parse(normalized);
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`${fieldName} must be a JSON object.`);
  }
  return parsed as Record<string, unknown>;
}

export function parseJsonArray(value: string, fieldName: string): unknown[] {
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed)) {
    throw new Error(`${fieldName} must be a JSON array.`);
  }
  return parsed;
}
