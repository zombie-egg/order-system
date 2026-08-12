import type { CartLine, KioskOrder, PaymentStatus } from './types';

export function formatMoney(amountMinor: number, currency: string, locale = 'nl-NL'): string {
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
  }).format(amountMinor / 100);
}

export function cartLineTotal(line: CartLine): number {
  const optionDelta = line.selectedOptions.reduce(
    (total, option) => total + option.value.price_delta_minor,
    0,
  );
  return (line.product.price_minor + optionDelta) * line.quantity;
}

export function latestPaymentAttempt(order: KioskOrder) {
  return order.payment_attempts.at(-1) ?? null;
}

export function paymentStatusLabel(status: PaymentStatus): string {
  const labels: Record<PaymentStatus, string> = {
    UNPAID: 'Niet betaald',
    INITIATED: 'Betaling gestart',
    AUTHORIZING: 'Wordt gecontroleerd',
    PAID: 'Betaald',
    FAILED: 'Niet gelukt',
    UNKNOWN: 'Controle nodig',
    REFUND_PENDING: 'Terugbetaling gestart',
    PARTIALLY_REFUNDED: 'Deels terugbetaald',
    REFUNDED: 'Terugbetaald',
  };
  return labels[status];
}

export function createIdempotencyKey(scope: string): string {
  const id =
    typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `kiosk-${scope}-${id}`;
}

export function allergenNames(data: Record<string, unknown>): string[] {
  const candidates = [data.contains, data.allergens, data.names];
  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      return candidate.filter((item): item is string => typeof item === 'string');
    }
  }
  return [];
}
