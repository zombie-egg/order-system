import { useCallback } from 'react';
import { ApiError, type ApiClient } from '../api';
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components';
import { shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type { StoreOperationsSummary, StoreWithPolicy } from '../types';

export function DashboardPage({
  api,
  canReadOrganization,
}: {
  api: ApiClient;
  canReadOrganization: boolean;
}) {
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
        title="Operations overview"
        description="Current exceptions and work queues across assigned stores."
        actions={
          <button className="button button-secondary" type="button" onClick={resource.reload}>
            Refresh
          </button>
        }
      />
      {resource.loading ? <LoadingState label="Loading operational status…" /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data && resource.data.operations.length === 0 ? (
        <EmptyState
          title="No assigned stores"
          detail="Your account does not currently have an assigned store."
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
                    <h2>{store?.store.name ?? `Store ${shortId(item.store_id)}`}</h2>
                    <p>{store ? `${store.store.code} · ${store.store.timezone}` : item.store_id}</p>
                  </div>
                  {store ? <StatusBadge value={store.policy.accepting_orders} /> : null}
                </header>
                <dl className="metric-grid">
                  <div>
                    <dt>Open orders</dt>
                    <dd>{item.open_orders}</dd>
                  </div>
                  <div>
                    <dt>Open tickets</dt>
                    <dd>{item.open_tickets}</dd>
                  </div>
                  <div>
                    <dt>Manual reviews</dt>
                    <dd>{item.open_manual_reviews}</dd>
                  </div>
                  <div>
                    <dt>Unknown payments</dt>
                    <dd>{item.unknown_payments}</dd>
                  </div>
                  <div>
                    <dt>Paid without ticket</dt>
                    <dd>{item.paid_orders_without_tickets}</dd>
                  </div>
                  <div>
                    <dt>Pending outbox</dt>
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
