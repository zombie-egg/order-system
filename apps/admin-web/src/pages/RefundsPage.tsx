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

export function RefundsPage({
  api,
  canResolve,
  canReconcile,
}: {
  api: ApiClient;
  canResolve: boolean;
  canReconcile: boolean;
}) {
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
        setSuccess(`Refund ${shortId(updated.id)} updated to ${updated.status}.`);
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
        title="Refunds"
        description="Monitor refund requests and explicitly execute or reconcile provider actions."
      />
      <MutationMessage error={mutationError} success={success} />
      {resource.loading ? <LoadingState label="Loading refunds…" /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState title="No refunds" detail="No refund request has been created." />
      ) : null}
      {resource.data?.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Refund</th>
                <th>Order</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Completed</th>
                <th>Actions</th>
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
                          Execute
                        </button>
                      ) : null}
                      {canReconcile && refund.status === 'UNKNOWN' ? (
                        <button
                          className="button button-secondary"
                          type="button"
                          disabled={pendingId === refund.id}
                          onClick={() => mutate(refund, 'reconcile')}
                        >
                          Reconcile
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
