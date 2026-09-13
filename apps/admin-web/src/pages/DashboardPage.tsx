import { useCallback, useMemo, useState } from 'react';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import type { ApiClient } from '../api';
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components';
import { TopNBarList } from '../components/charts';
import { formatMoneyMinor, shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type {
  DashboardKpi,
  MultiStoreSummary,
  Order,
  StoreOperationsSummary,
  StoreWithPolicy,
  TopProductsResponse,
} from '../types';
import { useAdminI18n } from '../i18n';

type DashboardRange = 'today' | 'this_week' | 'this_month';

interface BarDatum {
  name: string;
  value: number;
}

interface TrendPoint {
  label: string;
  value: number;
}

const CHART_COLORS = ['#e76f51', '#2a9d8f', '#7c83fd', '#d4a373', '#64748b', '#111827'];

function niceMax(value: number): number {
  if (value <= 0) return 100;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return step * magnitude;
}

function shortBucket(bucket: string): string {
  const week = bucket.match(/^\d{4}-W(\d{2})$/);
  if (week) return `W${week[1]}`;
  const month = bucket.match(/^\d{4}-(\d{2})$/);
  if (month) return `${month[1]}`;
  const date = bucket.match(/^\d{4}-(\d{2}-\d{2})$/);
  if (date) return `${date[1]}`;
  return bucket;
}

function axisMoney(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `€${(value / 1_000_000).toFixed(1)}m`;
  if (abs >= 1_000) return `€${(value / 1_000).toFixed(0)}k`;
  return `€${Math.round(value / 100)}`;
}

function plainAxis(value: number): string {
  return String(Math.round(value));
}

export function DashboardPage({
  api,
  canReadOrganization,
  stores,
  assignedStoreIds,
}: {
  api: ApiClient;
  canReadOrganization: boolean;
  stores: StoreWithPolicy[];
  assignedStoreIds: string[];
}) {
  const { t, choose, language } = useAdminI18n();
  const [range, setRange] = useState<DashboardRange>('today');
  const initialStores = useMemo(() => assignedStoreIds, [assignedStoreIds]);
  const [selectedStoreIds, setSelectedStoreIds] = useState<string[]>(initialStores);

  const storeName = useCallback(
    (storeId: string) => {
      const match = stores.find((entry) => entry.store.id === storeId);
      if (match) return match.store.name;
      return canReadOrganization ? t('assignedStore') : `${t('store')} ${shortId(storeId)}`;
    },
    [stores, canReadOrganization, t],
  );

  const loader = useCallback(async () => {
    const storeParams = new URLSearchParams();
    for (const storeId of selectedStoreIds) storeParams.append('store_ids', storeId);
    const storeQuery = storeParams.toString();

    const [kpiRaw, operations, orders] = await Promise.all([
      api.get<unknown>(`/admin/reports/dashboard${storeQuery ? `?${storeQuery}` : ''}`),
      api.get<StoreOperationsSummary[]>('/admin/reports/operations'),
      api.get<Order[]>('/admin/orders?limit=8'),
    ]);
    const kpi =
      kpiRaw && typeof kpiRaw === 'object' && !Array.isArray(kpiRaw) && Array.isArray((kpiRaw as DashboardKpi).stores)
        ? (kpiRaw as DashboardKpi)
        : null;

    let multiStore: MultiStoreSummary | null = null;
    let topProducts: TopProductsResponse | null = null;
    const tpQuery = new URLSearchParams({
      range: range === 'this_month' ? 'this_month' : 'this_week',
      order_by: 'quantity',
      limit: '5',
      locale: language,
    });
    if (range !== 'today') {
      const period = range === 'this_week' ? 'day' : 'week';
      const msQuery = new URLSearchParams({
        range: range === 'this_week' ? 'this_week' : 'this_month',
        period,
      });
      for (const storeId of selectedStoreIds) {
        msQuery.append('store_ids', storeId);
        tpQuery.append('store_ids', storeId);
      }
      const [multiRaw, topRaw] = await Promise.all([
        api.get<unknown>(`/admin/reports/multi-store?${msQuery.toString()}`),
        api.get<unknown>(`/admin/reports/top-products?${tpQuery.toString()}`),
      ]);
      multiStore =
        multiRaw &&
        typeof multiRaw === 'object' &&
        !Array.isArray(multiRaw) &&
        Array.isArray((multiRaw as MultiStoreSummary).stores)
          ? (multiRaw as MultiStoreSummary)
          : null;
      topProducts =
        topRaw && typeof topRaw === 'object' && !Array.isArray(topRaw) && Array.isArray((topRaw as TopProductsResponse).items)
          ? (topRaw as TopProductsResponse)
          : null;
    } else {
      for (const storeId of selectedStoreIds) tpQuery.append('store_ids', storeId);
      const topRaw = await api.get<unknown>(`/admin/reports/top-products?${tpQuery.toString()}`);
      topProducts =
        topRaw && typeof topRaw === 'object' && !Array.isArray(topRaw) && Array.isArray((topRaw as TopProductsResponse).items)
          ? (topRaw as TopProductsResponse)
          : null;
    }
    return { kpi, operations, multiStore, topProducts, orders };
  }, [api, selectedStoreIds, range, language]);

  const resource = useAsyncResource(loader);
  const { kpi, multiStore, topProducts } = resource.data ?? {};

  const perStore = useMemo(() => {
    if (!kpi || !Array.isArray(kpi.stores)) return [];
    if (multiStore && multiStore.stores.length > 0) {
      return multiStore.stores.map((entry) => ({
        name: entry.store_name ?? t('aggregate'),
        revenue: entry.gross_sales_minor,
        orders: entry.order_count,
      }));
    }
    return kpi.stores.map((entry) => ({
      name: entry.store_name ?? (entry.store_id ? storeName(entry.store_id) : t('aggregate')),
      revenue: entry.today_revenue_minor,
      orders: entry.today_order_count,
    }));
  }, [kpi, multiStore, storeName, t]);

  const revenueData: BarDatum[] = useMemo(
    () => perStore.map((entry) => ({ name: entry.name, value: entry.revenue })),
    [perStore],
  );
  const ordersData: BarDatum[] = useMemo(
    () => perStore.map((entry) => ({ name: entry.name, value: entry.orders })),
    [perStore],
  );
  const trendData: TrendPoint[] = useMemo(() => {
    if (!multiStore) return [];
    return multiStore.trend.map((bucket) => ({
      label: shortBucket(bucket.bucket),
      value: bucket.gross_sales_minor,
    }));
  }, [multiStore]);

  const totals = kpi?.totals;
  const currency = kpi?.currency ?? multiStore?.currency ?? 'EUR';
  const avgOrderValue =
    totals && totals.today_order_count > 0
      ? totals.today_revenue_minor / totals.today_order_count
      : null;
  const refundRate =
    multiStore && multiStore.totals.gross_sales_minor > 0
      ? (multiStore.totals.refunded_minor / multiStore.totals.gross_sales_minor) * 100
      : null;
  const maxRevenue = niceMax(Math.max(...revenueData.map((d) => d.value), 100));
  const maxOrders = niceMax(Math.max(...ordersData.map((d) => d.value), 10));
  const maxTrend = niceMax(Math.max(...trendData.map((d) => d.value), 100));

  const toggleStore = (storeId: string) => {
    setSelectedStoreIds((current) =>
      current.includes(storeId) ? current.filter((id) => id !== storeId) : [...current, storeId],
    );
  };
  const selectAllStores = () => setSelectedStoreIds(initialStores);

  return (
    <section>
      <PageHeader
        title={t('dashboard')}
        description={choose(
          '图表前置的经营概览：核心指标、多店销售趋势与工作队列一目了然。',
          'Operationeel overzicht met grafieken vooraan: kerncijfers, verkooptrend per vestiging en de werkqueue in één oogopslag.',
        )}
        actions={
          <button className="button button-secondary" type="button" onClick={resource.reload}>
            {t('refresh')}
          </button>
        }
      />

      {resource.loading ? (
        <LoadingState label={choose('正在加载经营状态…', 'Operationele status laden…')} />
      ) : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data && resource.data.operations.length === 0 ? (
        <EmptyState
          title={choose('暂无已分配门店', 'Geen toegewezen vestigingen')}
          detail={choose(
            '当前账号尚未被分配到任何门店。',
            'Aan dit account is nog geen vestiging toegewezen.',
          )}
        />
      ) : null}

      {resource.data && resource.data.operations.length > 0 ? (
        <>
          <div className="dashboard-tabs" role="tablist" aria-label={choose('仪表盘视图', 'Dashboardweergave')}>
            <button type="button" className="active" role="tab" aria-selected="true">{choose('概览', 'Overzicht')}</button>
            <button type="button" role="tab" aria-selected="false" onClick={() => setRange('this_week')}>{choose('分析', 'Analyse')}</button>
            <button type="button" role="tab" aria-selected="false" onClick={() => setRange('this_month')}>{choose('报表', 'Rapporten')}</button>
          </div>
          <div className="dashboard-controls">
            <div className="filter-chip-row" role="group" aria-label={t('reportPeriod')}>
              {(
                [
                  ['today', t('today')],
                  ['this_week', t('thisWeek')],
                  ['this_month', t('thisMonth')],
                ] as [DashboardRange, string][]
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
            {initialStores.length > 1 ? (
              <div className="store-check-list" aria-label={t('multiStore')}>
                {initialStores.map((storeId) => (
                  <label key={storeId}>
                    <input
                      type="checkbox"
                      checked={selectedStoreIds.includes(storeId)}
                      onChange={() => toggleStore(storeId)}
                    />
                    {storeName(storeId)}
                  </label>
                ))}
                <button type="button" className="link-button" onClick={selectAllStores}>
                  {t('allStores')}
                </button>
              </div>
            ) : null}
          </div>

          {kpi && totals ? (
            <section className="dashboard-kpi-grid" aria-label={choose('核心指标', 'Kerncijfers')}>
              <article className="card dashboard-kpi-card">
                <span>{choose('今日营收', t('todayRevenue'))}</span>
                <strong>{formatMoneyMinor(totals.today_revenue_minor, currency, language)}</strong>
                <small>{choose('营业日', 'Zaken-dag')} {kpi.business_date}</small>
              </article>
              <article className="card dashboard-kpi-card">
                <span>{choose('今日订单', t('todayOrders'))}</span>
                <strong>{totals.today_order_count}</strong>
                <small>{choose('已支付并进入履约流程', 'Betaald en naar uitvoering')}</small>
              </article>
              <article className="card dashboard-kpi-card">
                <span>{choose('平均订单金额', t('avgOrderValue'))}</span>
                <strong>{avgOrderValue !== null ? formatMoneyMinor(Math.round(avgOrderValue), currency, language) : '—'}</strong>
                <small>{choose('按今日营收计算', 'Op basis van de omzet vandaag')}</small>
              </article>
              <article className="card dashboard-kpi-card dashboard-kpi-wide">
                <span>{choose('实时履约状态', 'Live uitvoeringsstatus')}</span>
                <div className="kpi-inline-values">
                  <b>{totals.open_tickets}<small>{t('openTickets')}</small></b>
                  <b>{totals.open_manual_reviews}<small>{t('openReviews')}</small></b>
                  <b>{totals.unknown_payments}<small>{t('unknownPayments')}</small></b>
                </div>
              </article>
            </section>
          ) : null}

          <div className="card-grid dashboard-charts">
            <article className="card chart-card">
              <header className="card-header">
                <h2>
                  {range === 'today'
                    ? choose('今日各店营收', 'Omzet vandaag per vestiging')
                    : t('recentSalesTrend')}
                </h2>
                <span className="muted">{currency}</span>
              </header>
              {trendData.length > 0 ? (
                <ResponsiveContainer width="100%" height={230}>
                  <AreaChart data={trendData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <defs>
                      <linearGradient id="trendFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#e76f51" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#e76f51" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6ece9" />
                    <XAxis
                      dataKey="label"
                      tick={{ fontSize: 11, fill: '#637069' }}
                      axisLine={false}
                      tickLine={false}
                    />
                    <YAxis
                      tick={{ fontSize: 11, fill: '#637069' }}
                      axisLine={false}
                      tickLine={false}
                      width={52}
                      tickFormatter={(value: number) => axisMoney(value)}
                      domain={[0, maxTrend]}
                    />
                    <Tooltip
                      content={<MoneyTip formatValue={(v) => formatMoneyMinor(v, currency, language)} />}
                    />
                    <Area
                      type="monotone"
                      dataKey="value"
                      stroke="#e76f51"
                      strokeWidth={2.2}
                      fill="url(#trendFill)"
                      connectNulls
                    />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <SimpleBarChart
                  data={revenueData}
                  max={maxRevenue}
                  color="#e76f51"
                  formatValue={(v) => formatMoneyMinor(v, currency, language)}
                />
              )}
            </article>

            <article className="card chart-card">
              <header className="card-header">
                <h2>
                  {range === 'today'
                    ? choose('今日各店订单', 'Bestellingen vandaag per vestiging')
                    : t('storeSalesCompare')}
                </h2>
                <span className="muted">
                  {range === 'this_week' ? t('thisWeek') : range === 'this_month' ? t('thisMonth') : t('today')}
                </span>
              </header>
              <SimpleBarChart
                data={range === 'today' ? ordersData : revenueData}
                max={range === 'today' ? maxOrders : maxRevenue}
                color="#2a9d8f"
                tickFormatter={range === 'today' ? plainAxis : axisMoney}
                formatValue={(v) =>
                  range === 'today' ? `${v}` : formatMoneyMinor(v, currency, language)
                }
              />
            </article>
          </div>

          <div className="card-grid dashboard-lower">
            <article className="card chart-card">
              <header className="card-header">
                <h2>{t('topProducts')} 5</h2>
                <span className="muted">
                  {range === 'this_month' ? t('thisMonth') : t('thisWeek')}
                </span>
              </header>
              {topProducts && topProducts.items.length > 0 ? (
                <TopNBarList
                  items={topProducts.items.map((item) => ({
                    name: item.name,
                    value: item.quantity,
                    detail: formatMoneyMinor(item.revenue_minor, topProducts.currency, language),
                  }))}
                  formatValue={(value) => `${value}`}
                />
              ) : (
                <p className="muted standalone-message">
                  {choose('暂无商品销量数据', 'Nog geen verkoopgegevens voor producten.')}
                </p>
              )}
            </article>

            <article className="card chart-card">
              <header className="card-header">
                <h2>{t('workQueue')}</h2>
                <span className="muted">{choose('实时工作负载', 'Actuele werkbelasting')}</span>
              </header>
              <dl className="compact-list dashboard-queue">
                {resource.data?.operations.map((item) => {
                  const storeLabel = item.store_id ? storeName(item.store_id) : t('store');
                  return (
                    <div key={item.store_id}>
                      <dt>{storeLabel}</dt>
                      <dd className="queue-metrics">
                        <span>
                          {t('openOrders')} <strong>{item.open_orders}</strong>
                        </span>
                        <span>
                          {t('ticketCount')} <strong>{item.open_tickets}</strong>
                        </span>
                        <span>
                          {t('openReviews')} <strong>{item.open_manual_reviews}</strong>
                        </span>
                        <span>
                          {t('unknownPayments')} <strong>{item.unknown_payments}</strong>
                        </span>
                        <span>
                          {t('paidWithoutTicket')} <strong>{item.paid_orders_without_tickets}</strong>
                        </span>
                        <span>
                          {t('pendingOutbox')} <strong>{item.pending_outbox_events}</strong>
                        </span>
                      </dd>
                    </div>
                  );
                })}
              </dl>
              {refundRate !== null ? (
                <p className="muted dashboard-footnote">
                  {choose('退款率', 'Terugbetalingspercentage')}: <strong>{refundRate.toFixed(1)}%</strong>
                </p>
              ) : null}
            </article>
          </div>

          <article className="card dashboard-orders-card">
            <header className="card-header">
              <div>
                <h2>{choose('最近订单与支付', 'Recente bestellingen en betalingen')}</h2>
                <p>{choose('真实订单、支付和履约状态', 'Actuele bestel-, betaal- en uitvoeringsstatus')}</p>
              </div>
              <span className="muted">{resource.data.orders.length} {choose('条', 'regels')}</span>
            </header>
            <div className="table-wrap">
              <table>
                <thead><tr><th>{choose('订单', 'Bestelling')}</th><th>{choose('门店', 'Vestiging')}</th><th>{choose('支付', 'Betaling')}</th><th>{choose('订单状态', 'Status')}</th><th>{choose('金额', 'Bedrag')}</th><th>{choose('时间', 'Tijd')}</th></tr></thead>
                <tbody>
                  {resource.data.orders.map((order) => (
                    <tr key={order.id}>
                      <td><strong>#{order.display_number}</strong><small>{order.items.map((item) => `${item.quantity}× ${item.name}`).join(', ')}</small></td>
                      <td>{storeName(order.store_id)}</td>
                      <td><StatusBadge value={order.payment_status} /></td>
                      <td><StatusBadge value={order.status} /></td>
                      <td>{formatMoneyMinor(order.total_minor, order.currency, language)}</td>
                      <td>{order.confirmed_at ? new Date(order.confirmed_at).toLocaleString(language) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>
        </>
      ) : null}
    </section>
  );
}

function MoneyTip({
  active,
  payload,
  label,
  formatValue,
}: {
  active?: boolean;
  payload?: ReadonlyArray<{ value?: number | string }>;
  label?: string | number;
  formatValue: (value: number) => string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0];
  if (!point) return null;
  const value = typeof point.value === 'number' ? point.value : Number(point.value ?? 0);
  return (
    <div className="chart-tooltip">
      <strong>{String(label)}</strong>
      <span>{formatValue(value)}</span>
    </div>
  );
}

function SimpleBarChart({
  data,
  max,
  color,
  formatValue,
  tickFormatter = axisMoney,
}: {
  data: BarDatum[];
  max: number;
  color: string;
  formatValue: (value: number) => string;
  tickFormatter?: (value: number) => string;
}) {
  if (data.length === 0) {
    return <p className="muted standalone-message">—</p>;
  }
  return (
    <ResponsiveContainer width="100%" height={230}>
      <BarChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e6ece9" />
        <XAxis
          dataKey="name"
          tick={{ fontSize: 11, fill: '#637069' }}
          axisLine={false}
          tickLine={false}
          interval={0}
        />
        <YAxis
          tick={{ fontSize: 11, fill: '#637069' }}
          axisLine={false}
          tickLine={false}
          width={52}
          tickFormatter={tickFormatter}
          domain={[0, max]}
        />
        <Tooltip
          cursor={{ fill: 'rgba(67, 164, 118, 0.08)' }}
          content={<MoneyTip formatValue={formatValue} />}
        />
        <Bar dataKey="value" radius={[6, 6, 0, 0]} maxBarSize={46}>
          {data.map((entry, index) => (
            <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length] ?? color} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
