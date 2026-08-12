import { formatMoney } from './format';
import type { KioskReceipt } from './types';

interface ReceiptViewProps {
  receipt: KioskReceipt;
}

function objectValue(value: unknown): Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === 'string' ? value : null;
}

export function ReceiptView({ receipt }: ReceiptViewProps) {
  const document = receipt.document;
  const legalEntity = objectValue(document.legal_entity);
  const store = objectValue(document.store);
  const order = objectValue(document.order);
  const amounts = objectValue(document.amounts);
  const items = Array.isArray(document.items) ? document.items.map(objectValue) : [];
  const total = numberValue(amounts.total_minor) ?? numberValue(document.amount_minor);

  return (
    <section className="receipt" aria-labelledby="receipt-title">
      <div className="receipt-heading">
        <div>
          <p className="eyebrow">Digitaal bewijs</p>
          <h2 id="receipt-title">
            {receipt.receipt_type === 'SALE' ? 'Betaalbewijs' : 'Terugbetalingsbewijs'}
          </h2>
        </div>
        <span>{receipt.receipt_number}</span>
      </div>

      {(stringValue(legalEntity.name) ?? stringValue(store.name)) && (
        <p>
          <strong>{stringValue(legalEntity.name) ?? stringValue(store.name)}</strong>
          {stringValue(legalEntity.vat_number) && ` · BTW ${stringValue(legalEntity.vat_number)}`}
        </p>
      )}
      {(stringValue(order.order_number) ?? stringValue(document.order_number)) && (
        <p>Bestelling {stringValue(order.order_number) ?? stringValue(document.order_number)}</p>
      )}

      {items.length > 0 && (
        <ul className="receipt-lines">
          {items.map((item, index) => (
            <li key={`${String(item.line_number)}-${index}`}>
              <span>
                {numberValue(item.quantity) ?? 1}× {stringValue(item.name) ?? 'Product'}
              </span>
              <strong>
                {formatMoney(
                  numberValue(item.line_total_minor) ?? 0,
                  receipt.currency,
                  receipt.locale,
                )}
              </strong>
            </li>
          ))}
        </ul>
      )}

      {total !== null && (
        <p className="receipt-total">
          <span>{receipt.receipt_type === 'SALE' ? 'Totaal' : 'Terugbetaald'}</span>
          <strong>{formatMoney(total, receipt.currency, receipt.locale)}</strong>
        </p>
      )}
      <p className="receipt-date">
        Aangemaakt{' '}
        {new Intl.DateTimeFormat(receipt.locale, {
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(new Date(receipt.generated_at))}
      </p>
    </section>
  );
}
