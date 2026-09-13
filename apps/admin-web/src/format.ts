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

export function formatCompactNumber(value: number, locale = 'nl-NL'): string {
  try {
    return new Intl.NumberFormat(locale, {
      notation: 'compact',
      maximumFractionDigits: 1,
    }).format(value);
  } catch {
    return String(value);
  }
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

export async function resizeImageToDataUrl(
  file: File,
  maxDimension = 900,
  quality = 0.82,
): Promise<string> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === 'string') resolve(reader.result);
      else reject(new Error('The selected file could not be read as a data URL.'));
    };
    reader.onerror = () => reject(reader.error ?? new Error('The selected file could not be read.'));
    reader.readAsDataURL(file);
  });
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('This file could not be decoded as an image.'));
    img.src = dataUrl;
  });
  const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight));
  const width = Math.max(1, Math.round(image.naturalWidth * scale));
  const height = Math.max(1, Math.round(image.naturalHeight * scale));
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const context = canvas.getContext('2d');
  if (!context) {
    throw new Error('Image resizing is not supported in this browser.');
  }
  context.drawImage(image, 0, 0, width, height);
  const resized = canvas.toDataURL('image/jpeg', quality);
  const bytes = Math.round((resized.length - 'data:image/jpeg;base64,'.length) * 0.75);
  if (bytes > 4_800_000) {
    throw new Error('The image is too large after resizing. Please use a smaller image.');
  }
  return resized;
}
