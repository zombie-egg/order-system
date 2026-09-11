import { formatMoney } from './format';
import type { KioskReceipt } from './types';

interface ReceiptViewProps {
  receipt: KioskReceipt;
  language: 'zh-CN' | 'nl-NL';
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

export function ReceiptView({ receipt, language }: ReceiptViewProps) {
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
          <p className="eyebrow">{language === 'zh-CN' ? '电子凭证' : 'Digitaal bewijs'}</p>
          <h2 id="receipt-title">
            {receipt.receipt_type === 'SALE'
              ? language === 'zh-CN' ? '支付凭证' : 'Betaalbewijs'
              : language === 'zh-CN' ? '退款凭证' : 'Terugbetalingsbewijs'}
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
        <p>{language === 'zh-CN' ? '订单' : 'Bestelling'} {stringValue(order.order_number) ?? stringValue(document.order_number)}</p>
      )}
      {stringValue(order.fulfillment_type) && (
        <p>
          <strong>
            {stringValue(order.fulfillment_type) === 'TAKEAWAY' ? 'Meenemen' : 'Hier eten'}
          </strong>
        </p>
      )}

      {items.length > 0 && (
        <ul className="receipt-lines">
          {items.map((item, index) => (
            <li key={`${String(item.line_number)}-${index}`}>
              <span>
                {numberValue(item.quantity) ?? 1}× {stringValue(item.name) ?? (language === 'zh-CN' ? '商品' : 'Product')}
                {Array.isArray(item.options) && item.options.length > 0 && (
                  <small>
                    {item.options
                      .map(objectValue)
                      .map((option) => `${stringValue(option.group_name) ?? ''}: ${stringValue(option.name) ?? ''}`)
                      .join(', ')}
                  </small>
                )}
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

      {(numberValue(amounts.packaging_fee_minor) ?? 0) > 0 && (
        <p className="receipt-fee">
          <span>Verpakkingskosten</span>
          <strong>
            {formatMoney(
              numberValue(amounts.packaging_fee_minor) ?? 0,
              receipt.currency,
              receipt.locale,
            )}
          </strong>
        </p>
      )}

      {total !== null && (
        <p className="receipt-total">
          <span>{receipt.receipt_type === 'SALE' ? (language === 'zh-CN' ? '合计' : 'Totaal') : (language === 'zh-CN' ? '已退款' : 'Terugbetaald')}</span>
          <strong>{formatMoney(total, receipt.currency, receipt.locale)}</strong>
        </p>
      )}
      <p className="receipt-date">
        {language === 'zh-CN' ? '生成时间 ' : 'Aangemaakt '}
        {new Intl.DateTimeFormat(receipt.locale, {
          dateStyle: 'medium',
          timeStyle: 'short',
        }).format(new Date(receipt.generated_at))}
      </p>
    </section>
  );
}
