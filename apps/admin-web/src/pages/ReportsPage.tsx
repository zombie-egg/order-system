import { useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
import { ErrorState, Field, PageHeader, SubmitButton } from '../components';
import { formText } from '../form';
import { formatDuration, formatMoneyMinor, localInputToIso, toLocalDateTimeInput } from '../format';
import type { ReportsBundle, StoreWithPolicy } from '../types';
import { useAdminI18n } from '../i18n';

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
  const { t, choose } = useAdminI18n();
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
      if (start >= end) throw new Error(choose('报表结束时间必须晚于开始时间。', 'Het einde van het rapport moet na de start liggen.'));
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
        title={t('reports')}
        description={choose('销售、退款、履约和对账汇总使用左闭右开的时间范围。', 'Verkoop-, terugbetalings-, fulfilment- en afstemmingsoverzichten gebruiken een halfopen tijdvenster.')}
      />
      <form className="filter-bar" onSubmit={load}>
        <Field label={t('store')} htmlFor="report_store">
          <select id="report_store" name="store_id" required defaultValue={query.storeId}>
            <option value="" disabled>
              {t('selectStore')}
            </option>
            {stores.map(({ store }) => (
              <option key={store.id} value={store.id}>
                {store.name}
              </option>
            ))}
            {unnamedStoreIds.map((storeId) => (
              <option key={storeId} value={storeId}>
                {canReadOrganization ? t('assignedStore') : t('store')} {storeId.slice(0, 8)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={choose('开始时间', 'Start')} htmlFor="start_at">
          <input
            id="start_at"
            name="start_at"
            type="datetime-local"
            defaultValue={query.startAt}
            required
          />
        </Field>
        <Field label={choose('结束时间', 'Einde')} htmlFor="end_at">
          <input
            id="end_at"
            name="end_at"
            type="datetime-local"
            defaultValue={query.endAt}
            required
          />
        </Field>
        <SubmitButton pending={pending}>{choose('生成报表', 'Rapporten uitvoeren')}</SubmitButton>
      </form>
      {error ? <ErrorState error={error} /> : null}
      {reports ? (
        <div className="card-grid reports-grid">
          <article className="card">
            <h2>{choose('销售', 'Verkoop')}</h2>
            <dl className="metric-grid">
              <div>
                <dt>{t('orders')}</dt>
                <dd>{reports.sales.order_count}</dd>
              </div>
              <div>
                <dt>{choose('销售总额', 'Bruto-omzet')}</dt>
                <dd>{formatMoneyMinor(reports.sales.gross_sales_minor, reports.sales.currency)}</dd>
              </div>
              <div>
                <dt>{choose('优惠', 'Korting')}</dt>
                <dd>{formatMoneyMinor(reports.sales.discount_minor, reports.sales.currency)}</dd>
              </div>
              <div>
                <dt>{choose('实收金额', 'Netto ontvangen')}</dt>
                <dd>
                  {formatMoneyMinor(reports.sales.net_collected_minor, reports.sales.currency)}
                </dd>
              </div>
            </dl>
          </article>
          <article className="card">
            <h2>{t('refunds')}</h2>
            <dl className="metric-grid">
              <div>
                <dt>{choose('申请数', 'Verzoeken')}</dt>
                <dd>{reports.refunds.refund_count}</dd>
              </div>
              <div>
                <dt>{choose('申请金额', 'Aangevraagd')}</dt>
                <dd>
                  {formatMoneyMinor(reports.refunds.requested_minor, reports.refunds.currency)}
                </dd>
              </div>
              <div>
                <dt>{choose('成功金额', 'Geslaagd')}</dt>
                <dd>
                  {formatMoneyMinor(reports.refunds.succeeded_minor, reports.refunds.currency)}
                </dd>
              </div>
            </dl>
            <KeyValueList values={reports.refunds.status_counts} />
          </article>
          <article className="card">
            <h2>{choose('履约', 'Fulfilment')}</h2>
            <dl className="metric-grid">
              <div>
                <dt>{choose('制作单', 'Tickets')}</dt>
                <dd>{reports.fulfillment.ticket_count}</dd>
              </div>
              <div>
                <dt>{choose('平均接单时间', 'Gem. acceptatietijd')}</dt>
                <dd>{formatDuration(reports.fulfillment.average_seconds_to_acknowledge)}</dd>
              </div>
              <div>
                <dt>{choose('平均完成时间', 'Gem. klaartijd')}</dt>
                <dd>{formatDuration(reports.fulfillment.average_seconds_to_ready)}</dd>
              </div>
              <div>
                <dt>{choose('平均取餐时间', 'Gem. afhaaltijd')}</dt>
                <dd>{formatDuration(reports.fulfillment.average_seconds_ready_to_collect)}</dd>
              </div>
            </dl>
            <KeyValueList values={reports.fulfillment.status_counts} />
          </article>
          <article className="card">
            <h2>{choose('对账', 'Afstemming')}</h2>
            <dl className="metric-grid">
              <div>
                <dt>{choose('执行次数', 'Uitvoeringen')}</dt>
                <dd>{reports.reconciliation.run_count}</dd>
              </div>
              <div>
                <dt>{choose('失败次数', 'Mislukt')}</dt>
                <dd>{reports.reconciliation.failed_run_count}</dd>
              </div>
              <div>
                <dt>{choose('待处理问题', 'Open problemen')}</dt>
                <dd>{reports.reconciliation.open_issue_count}</dd>
              </div>
              <div>
                <dt>{choose('严重问题', 'Kritieke problemen')}</dt>
                <dd>{reports.reconciliation.critical_open_issue_count}</dd>
              </div>
            </dl>
            <p>{choose('最新状态：', 'Laatste status: ')}{reports.reconciliation.latest_run_status ?? '—'}</p>
          </article>
        </div>
      ) : (
        <p className="muted standalone-message">{choose('请选择门店和时间范围后生成报表。', 'Kies een vestiging en tijdvenster om rapporten uit te voeren.')}</p>
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
