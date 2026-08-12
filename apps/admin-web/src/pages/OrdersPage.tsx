import { useCallback, useEffect, useState } from 'react';
import type { ApiClient } from '../api';
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components';
import { formatDateTime, formatMoneyMinor } from '../format';
import { useAsyncResource } from '../hooks';
import type { Order } from '../types';

export function OrdersPage({ api }: { api: ApiClient }) {
  const loader = useCallback(() => api.get<Order[]>('/admin/orders?limit=200'), [api]);
  const resource = useAsyncResource(loader);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedId && resource.data?.[0]) setSelectedId(resource.data[0].id);
  }, [resource.data, selectedId]);
  const selected = resource.data?.find((order) => order.id === selectedId) ?? null;

  return (
    <section>
      <PageHeader
        title="Orders"
        description="Read-only order, item, and payment-attempt history for assigned stores."
        actions={
          <button type="button" className="button button-secondary" onClick={resource.reload}>
            Refresh
          </button>
        }
      />
      {resource.loading ? <LoadingState label="Loading orders…" /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState title="No orders" detail="No orders are available for the assigned stores." />
      ) : null}
      {resource.data?.length ? (
        <div className="split-layout split-wide">
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Order</th>
                  <th>Payment</th>
                  <th>Total</th>
                  <th>Date</th>
                </tr>
              </thead>
              <tbody>
                {resource.data.map((order) => (
                  <tr
                    key={order.id}
                    className={selectedId === order.id ? 'row-selected' : ''}
                    onClick={() => setSelectedId(order.id)}
                  >
                    <td>
                      <button
                        type="button"
                        className="table-link"
                        onClick={() => setSelectedId(order.id)}
                      >
                        {order.display_number}
                        <span>{order.order_number}</span>
                      </button>
                    </td>
                    <td>
                      <StatusBadge value={order.payment_status} />
                    </td>
                    <td>{formatMoneyMinor(order.total_minor, order.currency, order.locale)}</td>
                    <td>{order.business_date}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {selected ? <OrderDetail order={selected} /> : null}
        </div>
      ) : null}
    </section>
  );
}

function OrderDetail({ order }: { order: Order }) {
  return (
    <article className="card order-detail">
      <header className="card-header">
        <div>
          <h2>Order {order.display_number}</h2>
          <p className="monospace">{order.id}</p>
        </div>
        <div className="status-stack">
          <StatusBadge value={order.status} />
          <StatusBadge value={order.payment_status} />
        </div>
      </header>
      <dl className="metric-grid">
        <div>
          <dt>Total</dt>
          <dd>{formatMoneyMinor(order.total_minor, order.currency, order.locale)}</dd>
        </div>
        <div>
          <dt>Paid</dt>
          <dd>{formatMoneyMinor(order.paid_minor, order.currency, order.locale)}</dd>
        </div>
        <div>
          <dt>Refunded</dt>
          <dd>{formatMoneyMinor(order.refunded_minor, order.currency, order.locale)}</dd>
        </div>
        <div>
          <dt>Tax</dt>
          <dd>{formatMoneyMinor(order.tax_minor, order.currency, order.locale)}</dd>
        </div>
      </dl>
      <h3>Items</h3>
      <ul className="item-list">
        {order.items.map((item) => (
          <li key={item.id}>
            <div>
              <strong>
                {item.quantity} × {item.name}
              </strong>
              <span>{item.sku}</span>
              {item.options.map((option) => (
                <small key={option.option_value_id}>
                  {option.group_name}: {option.name}
                </small>
              ))}
            </div>
            <strong>{formatMoneyMinor(item.line_total_minor, order.currency, order.locale)}</strong>
          </li>
        ))}
      </ul>
      <h3>Payment attempts</h3>
      {order.payment_attempts.length === 0 ? (
        <p className="muted">No payment attempt recorded.</p>
      ) : (
        <ul className="item-list">
          {order.payment_attempts.map((attempt) => (
            <li key={attempt.id}>
              <div>
                <strong>
                  Attempt {attempt.attempt_number} · {attempt.provider}
                </strong>
                <span>
                  {attempt.payment_method} · {formatDateTime(attempt.requested_at)}
                </span>
                {attempt.failure_code ? <small>Failure: {attempt.failure_code}</small> : null}
              </div>
              <StatusBadge value={attempt.status} />
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
