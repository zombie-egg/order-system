import { useCallback, useState } from 'react';
import type { ApiClient } from '../api';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MutationMessage,
  PageHeader,
  StatusBadge,
} from '../components';
import { formatDateTime, formatMoneyMinor, shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type { Refund } from '../types';
import { useAdminI18n } from '../i18n';

export function RefundsPage({
  api,
  canResolve,
  canReconcile,
}: {
  api: ApiClient;
  canResolve: boolean;
  canReconcile: boolean;
}) {
  const { t, choose } = useAdminI18n();
  const loader = useCallback(() => api.get<Refund[]>('/admin/payments/refunds?limit=200'), [api]);
  const resource = useAsyncResource(loader);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const mutate = (refund: Refund, mode: 'execute' | 'reconcile') => {
    setPendingId(refund.id);
    setMutationError(null);
    setSuccess(null);
    void api.post<Refund>(`/admin/payments/refunds/${refund.id}/${mode}`).then(
      (updated) => {
        resource.setData(
          (current) => current?.map((entry) => (entry.id === updated.id ? updated : entry)) ?? null,
        );
        setPendingId(null);
        setSuccess(choose(`退款 ${shortId(updated.id)} 已更新为 ${updated.status}。`, `Terugbetaling ${shortId(updated.id)} is bijgewerkt naar ${updated.status}.`));
      },
      (error: unknown) => {
        setPendingId(null);
        setMutationError(error);
      },
    );
  };

  return (
    <section>
      <PageHeader
        title={t('refunds')}
        description={choose('查看退款申请，并执行或对账支付渠道操作。', 'Bekijk terugbetalingsverzoeken en voer betaalprovideracties uit of stem ze af.')}
      />
      <MutationMessage error={mutationError} success={success} />
      {resource.loading ? <LoadingState label={choose('正在加载退款…', 'Terugbetalingen laden…')} /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState title={choose('暂无退款申请', 'Geen terugbetalingen')} detail={choose('当前没有已创建的退款申请。', 'Er zijn geen terugbetalingsverzoeken aangemaakt.')} />
      ) : null}
      {resource.data?.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('refunds')}</th><th>{t('order')}</th><th>{t('amount')}</th><th>{t('status')}</th><th>{choose('完成时间', 'Voltooid')}</th><th>{t('actions')}</th>
              </tr>
            </thead>
            <tbody>
              {resource.data.map((refund) => (
                <tr key={refund.id}>
                  <td className="monospace">{shortId(refund.id)}</td>
                  <td className="monospace">{shortId(refund.order_id)}</td>
                  <td>{formatMoneyMinor(refund.amount_minor, refund.currency)}</td>
                  <td>
                    <StatusBadge value={refund.status} />
                    {refund.failure_code ? (
                      <small className="error-text">{refund.failure_code}</small>
                    ) : null}
                  </td>
                  <td>{formatDateTime(refund.completed_at)}</td>
                  <td>
                    <div className="button-row">
                      {canResolve && refund.status === 'PENDING' ? (
                        <button
                          className="button button-primary"
                          type="button"
                          disabled={pendingId === refund.id}
                          onClick={() => mutate(refund, 'execute')}
                        >
                          {choose('执行', 'Uitvoeren')}
                        </button>
                      ) : null}
                      {canReconcile && refund.status === 'UNKNOWN' ? (
                        <button
                          className="button button-secondary"
                          type="button"
                          disabled={pendingId === refund.id}
                          onClick={() => mutate(refund, 'reconcile')}
                        >
                          {choose('对账', 'Afstemmen')}
                        </button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
