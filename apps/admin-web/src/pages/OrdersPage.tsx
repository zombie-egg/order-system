import { useCallback, useState } from 'react';
import type { ApiClient } from '../api';
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components';
import { formatDateTime, formatMoneyMinor } from '../format';
import { useAsyncResource } from '../hooks';
import type { Order } from '../types';
import { useAdminI18n } from '../i18n';

export function OrdersPage({ api }: { api: ApiClient }) {
  const { t, choose } = useAdminI18n();
  const loader = useCallback(() => api.get<Order[]>('/admin/orders?limit=200'), [api]);
  const resource = useAsyncResource(loader);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const selected = resource.data?.find((order) => order.id === selectedId) ?? null;

  return (
    <section>
      <PageHeader
        title={t('orders')}
        description={choose('查看已分配门店的订单、商品与支付尝试记录。', 'Bekijk bestellingen, producten en betaalpogingen van toegewezen vestigingen.')}
        actions={
          <button type="button" className="button button-secondary" onClick={resource.reload}>
            {t('refresh')}
          </button>
        }
      />
      {resource.loading ? <LoadingState label={choose('正在加载订单…', 'Bestellingen laden…')} /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState title={choose('暂无订单', 'Geen bestellingen')} detail={choose('已分配门店目前没有可查看的订单。', 'Er zijn geen bestellingen zichtbaar voor de toegewezen vestigingen.')} />
      ) : null}
      {resource.data?.length ? (
        selected ? (
          <OrderDetail order={selected} onBack={() => setSelectedId(null)} />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>{t('order')}</th><th>{t('payment')}</th><th>{t('total')}</th><th>{t('date')}</th>
                </tr>
              </thead>
              <tbody>
                {resource.data.map((order) => (
                  <tr key={order.id}>
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
        )
      ) : null}
    </section>
  );
}

function OrderDetail({ order, onBack }: { order: Order; onBack: () => void }) {
  const { t, choose } = useAdminI18n();
  return (
    <article className="card order-detail">
      <header className="card-header">
        <div>
          <h2>{t('order')} {order.display_number}</h2>
          <p className="monospace">{order.id}</p>
        </div>
        <div className="order-detail-actions">
          <div className="status-stack">
            <StatusBadge value={order.status} />
            <StatusBadge value={order.payment_status} />
          </div>
          <button type="button" className="button button-secondary" onClick={onBack}>
            {choose('返回订单列表', 'Terug naar bestellingen')}
          </button>
        </div>
      </header>
      <dl className="metric-grid">
        <div>
          <dt>{choose('用餐方式', 'Bestelwijze')}</dt>
          <dd>{order.fulfillment_type === 'TAKEAWAY' ? choose('打包', 'Meenemen') : choose('堂食', 'Hier eten')}</dd>
        </div>
        {order.packaging_fee_minor > 0 && (
          <div>
            <dt>{choose('包装费', 'Verpakkingskosten')}</dt>
            <dd>{formatMoneyMinor(order.packaging_fee_minor, order.currency, order.locale)}</dd>
          </div>
        )}
        <div>
          <dt>{t('total')}</dt>
          <dd>{formatMoneyMinor(order.total_minor, order.currency, order.locale)}</dd>
        </div>
        <div>
          <dt>{choose('已支付', 'Betaald')}</dt>
          <dd>{formatMoneyMinor(order.paid_minor, order.currency, order.locale)}</dd>
        </div>
        <div>
          <dt>{choose('已退款', 'Terugbetaald')}</dt>
          <dd>{formatMoneyMinor(order.refunded_minor, order.currency, order.locale)}</dd>
        </div>
        <div>
          <dt>{choose('税费', 'Belasting')}</dt>
          <dd>{formatMoneyMinor(order.tax_minor, order.currency, order.locale)}</dd>
        </div>
      </dl>
      <h3>{choose('商品', 'Producten')}</h3>
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
      <h3>{choose('支付尝试', 'Betaalpogingen')}</h3>
      {order.payment_attempts.length === 0 ? (
        <p className="muted">{choose('暂无支付尝试记录。', 'Geen betaalpoging geregistreerd.')}</p>
      ) : (
        <ul className="item-list">
          {order.payment_attempts.map((attempt) => (
            <li key={attempt.id}>
              <div>
                <strong>
                  {choose('第', 'Poging ')}{attempt.attempt_number}{choose(' 次', '')} · {attempt.provider}
                </strong>
                <span>
                  {attempt.payment_method} · {formatDateTime(attempt.requested_at)}
                </span>
                {attempt.failure_code ? <small>{choose('失败：', 'Mislukt: ')}{attempt.failure_code}</small> : null}
              </div>
              <StatusBadge value={attempt.status} />
            </li>
          ))}
        </ul>
      )}
    </article>
  );
}
