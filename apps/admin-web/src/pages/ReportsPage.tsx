import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
import { ErrorState, Field, LoadingState, PageHeader, SubmitButton } from '../components';
import { TopNBarList, TrendChart } from '../components/charts';
import {
  formatCompactNumber,
  formatDuration,
  formatMoneyMinor,
  localInputToIso,
  toLocalDateTimeInput,
} from '../format';
import type {
  MultiStoreSummary,
  ReportsBundle,
  StoreWithPolicy,
  TopProductsResponse,
} from '../types';
import { useAdminI18n } from '../i18n';

type RangePreset = 'this_week' | 'last_week' | 'this_month' | 'last_month' | 'custom';
type Granularity = 'day' | 'week' | 'month';

interface ReportWindow {
  start: string;
  end: string;
}

function currentWeekStart(): Date {
  const now = new Date();
  const day = (now.getDay() + 6) % 7; // Monday = 0
  const start = new Date(now);
  start.setDate(now.getDate() - day);
  start.setHours(0, 0, 0, 0);
  return start;
}

function defaultWindow(): ReportWindow {
  const end = new Date();
  return { start: toLocalDateTimeInput(currentWeekStart()), end: toLocalDateTimeInput(end) };
}

function buildWindowParams(
  range: RangePreset,
  customStart: string,
  customEnd: string,
): Record<string, string> {
  if (range === 'custom') {
    return { start_at: localInputToIso(customStart), end_at: localInputToIso(customEnd) };
  }
  return { range };
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
  const { t, choose, language } = useAdminI18n();
  const [range, setRange] = useState<RangePreset>('this_week');
  const [customStart, setCustomStart] = useState(defaultWindow().start);
  const [customEnd, setCustomEnd] = useState(defaultWindow().end);
  const [granularity, setGranularity] = useState<Granularity>('day');
  const [topOrderBy, setTopOrderBy] = useState<'quantity' | 'revenue'>('quantity');
  const topLimit = 5;

  const initialSelection = useMemo(() => assignedStoreIds, [assignedStoreIds]);
  const [selectedStoreIds, setSelectedStoreIds] = useState<string[]>(initialSelection);
  const [detailStoreId, setDetailStoreId] = useState<string>(assignedStoreIds[0] ?? '');

  const [multiStore, setMultiStore] = useState<MultiStoreSummary | null>(null);
  const [topProducts, setTopProducts] = useState<TopProductsResponse | null>(null);
  const [detail, setDetail] = useState<ReportsBundle | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const storeName = useCallback(
    (storeId: string) => {
      const match = stores.find(({ store }) => store.id === storeId);
      if (match) return match.store.name;
      return canReadOrganization ? t('assignedStore') : t('store');
    },
    [stores, canReadOrganization, t],
  );

  const loadAll = useCallback(
    (rangeValue: RangePreset, customStartValue: string, customEndValue: string) => {
      const windowParams = buildWindowParams(rangeValue, customStartValue, customEndValue);
      const multiParams = new URLSearchParams(windowParams);
      for (const storeId of selectedStoreIds) multiParams.append('store_ids', storeId);
      multiParams.set('period', granularity);
      const topParams = new URLSearchParams(windowParams);
      for (const storeId of selectedStoreIds) topParams.append('store_ids', storeId);
      topParams.set('order_by', topOrderBy);
      topParams.set('limit', String(topLimit));
      topParams.set('locale', language);
      setPending(true);
      setError(null);
      void Promise.all([
        api.get<MultiStoreSummary>(`/admin/reports/multi-store?${multiParams.toString()}`),
        api.get<TopProductsResponse>(`/admin/reports/top-products?${topParams.toString()}`),
      ]).then(
        ([summary, products]) => {
          setMultiStore(summary);
          setTopProducts(products);
          setPending(false);
        },
        (reason: unknown) => {
          setError(reason);
          setPending(false);
        },
      );
    },
    [api, selectedStoreIds, granularity, topOrderBy, topLimit, language],
  );

  const loadDetail = useCallback(
    (rangeValue: RangePreset, customStartValue: string, customEndValue: string) => {
      if (!detailStoreId) return;
      setPending(true);
      setError(null);
      const windowParams = new URLSearchParams(
        buildWindowParams(rangeValue, customStartValue, customEndValue),
      );
      const suffix = `?store_id=${detailStoreId}&${windowParams.toString()}`;
      void Promise.all([
        api.get<ReportsBundle['sales']>(`/admin/reports/sales${suffix}`),
        api.get<ReportsBundle['refunds']>(`/admin/reports/refunds${suffix}`),
        api.get<ReportsBundle['fulfillment']>(`/admin/reports/fulfillment${suffix}`),
        api.get<ReportsBundle['reconciliation']>(`/admin/reports/reconciliation${suffix}`),
      ]).then(
        ([sales, refunds, fulfillment, reconciliation]) => {
          setDetail({ sales, refunds, fulfillment, reconciliation });
          setPending(false);
        },
        (reason: unknown) => {
          setError(reason);
          setPending(false);
        },
      );
    },
    [api, detailStoreId],
  );

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      if (!range || !detailStoreId) return;
      const resolvedStart = range === 'custom' ? customStart : '';
      const resolvedEnd = range === 'custom' ? customEnd : '';
      loadAll(range, resolvedStart, resolvedEnd);
      loadDetail(range, resolvedStart, resolvedEnd);
    } catch (reason) {
      setError(reason);
    }
  };

  useEffect(() => {
    // Reactive refresh when the user toggles the store set, granularity, or ranking.
    const timer = window.setTimeout(() => {
      setPending(true);
      setError(null);
      loadAll(range, range === 'custom' ? customStart : '', range === 'custom' ? customEnd : '');
      loadDetail(range, range === 'custom' ? customStart : '', range === 'custom' ? customEnd : '');
    }, 250);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    range,
    customStart,
    customEnd,
    selectedStoreIds,
    granularity,
    topOrderBy,
    topLimit,
    detailStoreId,
  ]);

  const toggleStore = (storeId: string) => {
    setSelectedStoreIds((current) =>
      current.includes(storeId) ? current.filter((id) => id !== storeId) : [...current, storeId],
    );
  };

  const selectAllStores = () => setSelectedStoreIds(assignedStoreIds);

  const emptyStores = assignedStoreIds.length === 0;

  return (
    <section>
      <PageHeader
        title={t('reports')}
        description={choose(
          '多店汇总、热销排行与单店明细，支持本周/本月等快捷时间选择。',
          'Vestigingsoverzicht, topsellers en details per vestiging met snelkeuzes voor de periode.',
        )}
      />
      <form className="filter-bar" onSubmit={submit}>
        <Field label={choose('时间范围', 'Periode')} htmlFor="report_range">
          <div className="filter-chip-row">
            {(
              [
                ['this_week', t('thisWeek')],
                ['last_week', t('lastWeek')],
                ['this_month', t('thisMonth')],
                ['last_month', t('lastMonth')],
                ['custom', t('customRange')],
              ] as [RangePreset, string][]
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className={`filter-chip ${range === value ? 'active' : ''}`}
                onClick={() => setRange(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </Field>
        {range === 'custom' ? (
          <>
            <Field label={choose('开始时间', 'Start')} htmlFor="start_at">
              <input
                id="start_at"
                type="datetime-local"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                required
              />
            </Field>
            <Field label={choose('结束时间', 'Einde')} htmlFor="end_at">
              <input
                id="end_at"
                type="datetime-local"
                value={customEnd}
                onChange={(e) => setCustomEnd(e.target.value)}
                required
              />
            </Field>
          </>
        ) : null}
        <Field label={choose('图表粒度', 'Grafiekinterval')} htmlFor="report_granularity">
          <select
            id="report_granularity"
            value={granularity}
            onChange={(e) => setGranularity(e.target.value as Granularity)}
          >
            <option value="day">{choose('按天', 'Per dag')}</option>
            <option value="week">{choose('按周', 'Per week')}</option>
            <option value="month">{choose('按月', 'Per maand')}</option>
          </select>
        </Field>
        <SubmitButton pending={pending}>{choose('生成报表', 'Rapporten uitvoeren')}</SubmitButton>
      </form>
      {error ? <ErrorState error={error} /> : null}
      {emptyStores ? (
        <p className="muted standalone-message">
          {choose('当前账号未分配任何门店。', 'Aan dit account is geen vestiging toegewezen.')}
        </p>
      ) : (
        <>
          <div className="card">
            <header className="card-header">
              <div>
                <h2>
                  {multiStore ? `${t('store')} × ${multiStore.stores.length}` : t('multiStore')}
                </h2>
                <p>
                  {choose(
                    '勾选门店，一键查看销售/退款/履约汇总与趋势。',
                    'Selecteer vestigingen om verkoop-, terugbetalings- en fulfilmentsamenvattingen en de trend te zien.',
                  )}
                </p>
              </div>
              <button type="button" className="button button-secondary" onClick={selectAllStores}>
                {t('allStores')}
              </button>
            </header>
            <div className="store-check-list">
              {assignedStoreIds.map((storeId) => (
                <label key={storeId}>
                  <input
                    type="checkbox"
                    checked={selectedStoreIds.includes(storeId)}
                    onChange={() => toggleStore(storeId)}
                  />
                  {storeName(storeId)}
                </label>
              ))}
            </div>
            {selectedStoreIds.length === 0 ? (
              <p className="muted standalone-message">
                {choose('请至少选择一家门店。', 'Kies minimaal één vestiging.')}
              </p>
            ) : null}
            {multiStore?.stores.length === 0 ? (
              <LoadingState label={choose('暂无数据', 'Geen gegevens')} />
            ) : null}
          </div>

          {multiStore ? (
            <div className="card-grid">
              <article className="card chart-card">
                <h2>{choose('各店销售汇总', 'Verkoop per vestiging')}</h2>
                <table className="reports-multi-table">
                  <thead>
                    <tr>
                      <th>{t('store')}</th>
                      <th>{t('todayOrders')}</th>
                      <th>{choose('销售总额', 'Bruto-omzet')}</th>
                      <th>{choose('实收合计', 'Netto ontvangen')}</th>
                      <th>{choose('制作单', 'Tickets')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {multiStore.stores.map((entry) => (
                      <tr key={entry.store_id ?? 'total'}>
                        <td>{entry.store_name ?? t('aggregate')}</td>
                        <td>{entry.order_count}</td>
                        <td>
                          {formatMoneyMinor(entry.gross_sales_minor, multiStore.currency, language)}
                        </td>
                        <td>
                          {formatMoneyMinor(
                            entry.net_collected_minor,
                            multiStore.currency,
                            language,
                          )}
                        </td>
                        <td>{entry.ticket_count}</td>
                      </tr>
                    ))}
                    <tr>
                      <td>{t('aggregate')}</td>
                      <td>{multiStore.totals.order_count}</td>
                      <td>
                        {formatMoneyMinor(
                          multiStore.totals.gross_sales_minor,
                          multiStore.currency,
                          language,
                        )}
                      </td>
                      <td>
                        {formatMoneyMinor(
                          multiStore.totals.net_collected_minor,
                          multiStore.currency,
                          language,
                        )}
                      </td>
                      <td>{multiStore.totals.ticket_count}</td>
                    </tr>
                  </tbody>
                </table>
              </article>

              <article className="card chart-card">
                <h2>{t('trend')}</h2>
                <TrendChart
                  data={multiStore.trend.map((bucket) => ({
                    label: bucket.bucket,
                    value: bucket.gross_sales_minor,
                  }))}
                  formatValue={(value) => formatMoneyMinor(value, multiStore.currency, language)}
                  height={200}
                />
                <dl className="metric-grid">
                  <div>
                    <dt>{choose('订单数', 'Bestellingen')}</dt>
                    <dd>{multiStore.totals.order_count}</dd>
                  </div>
                  <div>
                    <dt>{choose('退款', 'Terugbetalingen')}</dt>
                    <dd>
                      {formatMoneyMinor(
                        multiStore.totals.refunded_minor,
                        multiStore.currency,
                        language,
                      )}
                    </dd>
                  </div>
                </dl>
              </article>
            </div>
          ) : pending && !error ? (
            <LoadingState label={choose('正在加载报表…', 'Rapporten laden…')} />
          ) : null}
          {multiStore && multiStore.trend.length > 0 ? null : null}

          <div className="card">
            <header className="card-header">
              <div>
                <h2>
                  {t('topProducts')} {topLimit}
                </h2>
                <p>
                  {choose(
                    '按销售数量或销售额排名，支持多店聚合。',
                    'Gerangschikt op verkochte aantallen of omzet, geaggregeerd over vestigingen.',
                  )}
                </p>
              </div>
              <label className="field-inline">
                {choose('排序', 'Sorteer op')}{' '}
                <select
                  value={topOrderBy}
                  onChange={(e) => setTopOrderBy(e.target.value as 'quantity' | 'revenue')}
                >
                  <option value="quantity">{t('sold')}</option>
                  <option value="revenue">{t('salesAmount')}</option>
                </select>
              </label>
            </header>
            {topProducts ? (
              <TopNBarList
                items={topProducts.items.map((item) => ({
                  name: item.name,
                  value: topOrderBy === 'quantity' ? item.quantity : item.revenue_minor,
                  detail:
                    topOrderBy === 'quantity'
                      ? `${formatMoneyMinor(item.revenue_minor, topProducts.currency, language)}`
                      : `${item.quantity} ${t('sold')}`,
                }))}
                formatValue={(value) =>
                  topOrderBy === 'quantity' ? `${value}` : formatCompactNumber(value)
                }
              />
            ) : null}
          </div>

          <div className="card">
            <header className="card-header">
              <div>
                <h2>{choose('单店明细报表', 'Detailrapport per vestiging')}</h2>
              </div>
              <Field label={t('store')} htmlFor="detail_store">
                <select
                  id="detail_store"
                  value={detailStoreId}
                  onChange={(e) => setDetailStoreId(e.target.value)}
                >
                  {assignedStoreIds.map((storeId) => (
                    <option key={storeId} value={storeId}>
                      {storeName(storeId)}
                    </option>
                  ))}
                </select>
              </Field>
            </header>
            {detail ? (
              <div className="card-grid reports-grid">
                <article className="card">
                  <h2>{choose('销售', 'Verkoop')}</h2>
                  <dl className="metric-grid">
                    <div>
                      <dt>{t('orders')}</dt>
                      <dd>{detail.sales.order_count}</dd>
                    </div>
                    <div>
                      <dt>{choose('销售总额', 'Bruto-omzet')}</dt>
                      <dd>
                        {formatMoneyMinor(
                          detail.sales.gross_sales_minor,
                          detail.sales.currency,
                          language,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{choose('优惠', 'Korting')}</dt>
                      <dd>
                        {formatMoneyMinor(
                          detail.sales.discount_minor,
                          detail.sales.currency,
                          language,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{choose('实收金额', 'Netto ontvangen')}</dt>
                      <dd>
                        {formatMoneyMinor(
                          detail.sales.net_collected_minor,
                          detail.sales.currency,
                          language,
                        )}
                      </dd>
                    </div>
                  </dl>
                </article>
                <article className="card">
                  <h2>{t('refunds')}</h2>
                  <dl className="metric-grid">
                    <div>
                      <dt>{choose('申请数', 'Verzoeken')}</dt>
                      <dd>{detail.refunds.refund_count}</dd>
                    </div>
                    <div>
                      <dt>{choose('申请金额', 'Aangevraagd')}</dt>
                      <dd>
                        {formatMoneyMinor(
                          detail.refunds.requested_minor,
                          detail.refunds.currency,
                          language,
                        )}
                      </dd>
                    </div>
                    <div>
                      <dt>{choose('成功金额', 'Geslaagd')}</dt>
                      <dd>
                        {formatMoneyMinor(
                          detail.refunds.succeeded_minor,
                          detail.refunds.currency,
                          language,
                        )}
                      </dd>
                    </div>
                  </dl>
                  <KeyValueList values={detail.refunds.status_counts} />
                </article>
                <article className="card">
                  <h2>{choose('履约', 'Fulfilment')}</h2>
                  <dl className="metric-grid">
                    <div>
                      <dt>{choose('制作单', 'Tickets')}</dt>
                      <dd>{detail.fulfillment.ticket_count}</dd>
                    </div>
                    <div>
                      <dt>{choose('平均接单时间', 'Gem. acceptatietijd')}</dt>
                      <dd>{formatDuration(detail.fulfillment.average_seconds_to_acknowledge)}</dd>
                    </div>
                    <div>
                      <dt>{choose('平均完成时间', 'Gem. klaartijd')}</dt>
                      <dd>{formatDuration(detail.fulfillment.average_seconds_to_ready)}</dd>
                    </div>
                    <div>
                      <dt>{choose('平均取餐时间', 'Gem. afhaaltijd')}</dt>
                      <dd>{formatDuration(detail.fulfillment.average_seconds_ready_to_collect)}</dd>
                    </div>
                  </dl>
                  <KeyValueList values={detail.fulfillment.status_counts} />
                </article>
                <article className="card">
                  <h2>{choose('对账', 'Afstemming')}</h2>
                  <dl className="metric-grid">
                    <div>
                      <dt>{choose('执行次数', 'Uitvoeringen')}</dt>
                      <dd>{detail.reconciliation.run_count}</dd>
                    </div>
                    <div>
                      <dt>{choose('失败次数', 'Mislukt')}</dt>
                      <dd>{detail.reconciliation.failed_run_count}</dd>
                    </div>
                    <div>
                      <dt>{choose('待处理问题', 'Open problemen')}</dt>
                      <dd>{detail.reconciliation.open_issue_count}</dd>
                    </div>
                    <div>
                      <dt>{choose('严重问题', 'Kritieke problemen')}</dt>
                      <dd>{detail.reconciliation.critical_open_issue_count}</dd>
                    </div>
                  </dl>
                </article>
              </div>
            ) : (
              <p className="muted standalone-message">
                {choose(
                  '请点击“生成报表”加载单店明细。',
                  'Klik op “Rapporten uitvoeren” om het detailrapport te laden.',
                )}
              </p>
            )}
          </div>
        </>
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
