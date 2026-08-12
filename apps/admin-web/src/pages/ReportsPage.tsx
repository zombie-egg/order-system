import { useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
import { ErrorState, Field, PageHeader, SubmitButton } from '../components';
import { formText } from '../form';
import { formatDuration, formatMoneyMinor, localInputToIso, toLocalDateTimeInput } from '../format';
import type { ReportsBundle, StoreWithPolicy } from '../types';

interface ReportQuery {
  storeId: string;
  startAt: string;
  endAt: string;
}

function defaultQuery(): ReportQuery {
  const end = new Date();
  const start = new Date(end.getTime() - 7 * 24 * 60 * 60 * 1000);
  return { storeId: '', startAt: toLocalDateTimeInput(start), endAt: toLocalDateTimeInput(end) };
}

export function ReportsPage({
  api,
  stores,
  assignedStoreIds,
  canReadOrganization,
}: {
  api: ApiClient;
  stores: StoreWithPolicy[];
  assignedStoreIds: string[];
  canReadOrganization: boolean;
}) {
  const [query, setQuery] = useState(defaultQuery);
  const [reports, setReports] = useState<ReportsBundle | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const namedStoreIds = new Set(stores.map(({ store }) => store.id));
  const unnamedStoreIds = assignedStoreIds.filter((storeId) => !namedStoreIds.has(storeId));

  const load = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const next = {
      storeId: formText(form, 'store_id'),
      startAt: formText(form, 'start_at'),
      endAt: formText(form, 'end_at'),
    };
    let params: URLSearchParams;
    try {
      const start = localInputToIso(next.startAt);
      const end = localInputToIso(next.endAt);
      if (start >= end) throw new Error('Report end must be later than report start.');
      params = new URLSearchParams({ store_id: next.storeId, start_at: start, end_at: end });
    } catch (reason) {
      setError(reason);
      return;
    }
    setQuery(next);
    setPending(true);
    setError(null);
    const suffix = `?${params.toString()}`;
    void Promise.all([
      api.get<ReportsBundle['sales']>(`/admin/reports/sales${suffix}`),
      api.get<ReportsBundle['refunds']>(`/admin/reports/refunds${suffix}`),
      api.get<ReportsBundle['fulfillment']>(`/admin/reports/fulfillment${suffix}`),
      api.get<ReportsBundle['reconciliation']>(`/admin/reports/reconciliation${suffix}`),
    ]).then(
      ([sales, refunds, fulfillment, reconciliation]) => {
        setReports({ sales, refunds, fulfillment, reconciliation });
        setPending(false);
      },
      (reason: unknown) => {
        setError(reason);
        setPending(false);
      },
    );
  };

  return (
    <section>
      <PageHeader
        title="Reports"
        description="Sales, refund, fulfillment, and reconciliation summaries use a half-open time window."
      />
      <form className="filter-bar" onSubmit={load}>
        <Field label="Store" htmlFor="report_store">
          <select id="report_store" name="store_id" required defaultValue={query.storeId}>
            <option value="" disabled>
              Select a store
            </option>
            {stores.map(({ store }) => (
              <option key={store.id} value={store.id}>
                {store.name}
              </option>
            ))}
            {unnamedStoreIds.map((storeId) => (
              <option key={storeId} value={storeId}>
                {canReadOrganization ? 'Assigned store' : 'Store'} {storeId.slice(0, 8)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Start" htmlFor="start_at">
          <input
            id="start_at"
            name="start_at"
            type="datetime-local"
            defaultValue={query.startAt}
            required
          />
        </Field>
        <Field label="End" htmlFor="end_at">
          <input
            id="end_at"
            name="end_at"
            type="datetime-local"
            defaultValue={query.endAt}
            required
          />
        </Field>
        <SubmitButton pending={pending}>Run reports</SubmitButton>
      </form>
      {error ? <ErrorState error={error} /> : null}
      {reports ? (
        <div className="card-grid reports-grid">
          <article className="card">
            <h2>Sales</h2>
            <dl className="metric-grid">
              <div>
                <dt>Orders</dt>
                <dd>{reports.sales.order_count}</dd>
              </div>
              <div>
                <dt>Gross sales</dt>
                <dd>{formatMoneyMinor(reports.sales.gross_sales_minor, reports.sales.currency)}</dd>
              </div>
              <div>
                <dt>Discount</dt>
                <dd>{formatMoneyMinor(reports.sales.discount_minor, reports.sales.currency)}</dd>
              </div>
              <div>
                <dt>Net collected</dt>
                <dd>
                  {formatMoneyMinor(reports.sales.net_collected_minor, reports.sales.currency)}
                </dd>
              </div>
            </dl>
          </article>
          <article className="card">
            <h2>Refunds</h2>
            <dl className="metric-grid">
              <div>
                <dt>Requests</dt>
                <dd>{reports.refunds.refund_count}</dd>
              </div>
              <div>
                <dt>Requested</dt>
                <dd>
                  {formatMoneyMinor(reports.refunds.requested_minor, reports.refunds.currency)}
                </dd>
              </div>
              <div>
                <dt>Succeeded</dt>
                <dd>
                  {formatMoneyMinor(reports.refunds.succeeded_minor, reports.refunds.currency)}
                </dd>
              </div>
            </dl>
            <KeyValueList values={reports.refunds.status_counts} />
          </article>
          <article className="card">
            <h2>Fulfillment</h2>
            <dl className="metric-grid">
              <div>
                <dt>Tickets</dt>
                <dd>{reports.fulfillment.ticket_count}</dd>
              </div>
              <div>
                <dt>Avg. acknowledge</dt>
                <dd>{formatDuration(reports.fulfillment.average_seconds_to_acknowledge)}</dd>
              </div>
              <div>
                <dt>Avg. ready</dt>
                <dd>{formatDuration(reports.fulfillment.average_seconds_to_ready)}</dd>
              </div>
              <div>
                <dt>Avg. collection</dt>
                <dd>{formatDuration(reports.fulfillment.average_seconds_ready_to_collect)}</dd>
              </div>
            </dl>
            <KeyValueList values={reports.fulfillment.status_counts} />
          </article>
          <article className="card">
            <h2>Reconciliation</h2>
            <dl className="metric-grid">
              <div>
                <dt>Runs</dt>
                <dd>{reports.reconciliation.run_count}</dd>
              </div>
              <div>
                <dt>Failed</dt>
                <dd>{reports.reconciliation.failed_run_count}</dd>
              </div>
              <div>
                <dt>Open issues</dt>
                <dd>{reports.reconciliation.open_issue_count}</dd>
              </div>
              <div>
                <dt>Critical issues</dt>
                <dd>{reports.reconciliation.critical_open_issue_count}</dd>
              </div>
            </dl>
            <p>Latest status: {reports.reconciliation.latest_run_status ?? '—'}</p>
          </article>
        </div>
      ) : (
        <p className="muted standalone-message">Select a store and time window to run reports.</p>
      )}
    </section>
  );
}

function KeyValueList({ values }: { values: Record<string, number> }) {
  return (
    <dl className="compact-list">
      {Object.entries(values).map(([key, value]) => (
        <div key={key}>
          <dt>{key.replaceAll('_', ' ')}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
