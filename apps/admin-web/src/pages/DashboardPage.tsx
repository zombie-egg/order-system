import { useCallback } from 'react';
import { ApiError, type ApiClient } from '../api';
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components';
import { shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type { StoreOperationsSummary, StoreWithPolicy } from '../types';
import { useAdminI18n } from '../i18n';

export function DashboardPage({
  api,
  canReadOrganization,
}: {
  api: ApiClient;
  canReadOrganization: boolean;
}) {
  const { t, choose } = useAdminI18n();
  const loader = useCallback(async () => {
    const operations = await api.get<StoreOperationsSummary[]>('/admin/reports/operations');
    const stores = canReadOrganization
      ? await api.get<StoreWithPolicy[]>('/admin/organization/stores').catch((error: unknown) => {
          if (error instanceof ApiError && error.status === 403) return [];
          throw error;
        })
      : [];
    return { operations, stores };
  }, [api, canReadOrganization]);
  const resource = useAsyncResource(loader);

  return (
    <section>
      <PageHeader
        title={t('dashboard')}
        description={choose('查看已分配门店的当前异常与工作队列。', 'Bekijk actuele uitzonderingen en werkqueues voor toegewezen vestigingen.')}
        actions={
          <button className="button button-secondary" type="button" onClick={resource.reload}>
            {t('refresh')}
          </button>
        }
      />
      {resource.loading ? <LoadingState label={choose('正在加载经营状态…', 'Operationele status laden…')} /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data && resource.data.operations.length === 0 ? (
        <EmptyState
          title={choose('暂无已分配门店', 'Geen toegewezen vestigingen')}
          detail={choose('当前账号尚未被分配到任何门店。', 'Aan dit account is nog geen vestiging toegewezen.')}
        />
      ) : null}
      {resource.data ? (
        <div className="card-grid">
          {resource.data.operations.map((item) => {
            const store = resource.data?.stores.find((entry) => entry.store.id === item.store_id);
            return (
              <article className="card" key={item.store_id}>
                <header className="card-header">
                  <div>
                    <h2>{store?.store.name ?? `${t('store')} ${shortId(item.store_id)}`}</h2>
                    <p>{store ? `${store.store.code} · ${store.store.timezone}` : item.store_id}</p>
                  </div>
                  {store ? <StatusBadge value={store.policy.accepting_orders} /> : null}
                </header>
                <dl className="metric-grid">
                  <div>
                    <dt>{choose('进行中的订单', 'Open bestellingen')}</dt>
                    <dd>{item.open_orders}</dd>
                  </div>
                  <div>
                    <dt>{choose('进行中的制作单', 'Open keukentickets')}</dt>
                    <dd>{item.open_tickets}</dd>
                  </div>
                  <div>
                    <dt>{choose('人工审核', 'Handmatige beoordelingen')}</dt>
                    <dd>{item.open_manual_reviews}</dd>
                  </div>
                  <div>
                    <dt>{choose('未知支付', 'Onbekende betalingen')}</dt>
                    <dd>{item.unknown_payments}</dd>
                  </div>
                  <div>
                    <dt>{choose('已支付但无制作单', 'Betaald zonder ticket')}</dt>
                    <dd>{item.paid_orders_without_tickets}</dd>
                  </div>
                  <div>
                    <dt>{choose('待发送事件', 'Openstaande uitgaande berichten')}</dt>
                    <dd>{item.pending_outbox_events}</dd>
                  </div>
                </dl>
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
