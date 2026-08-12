import { useCallback, useRef, useState, type FormEvent } from 'react';
import { createIdempotencyKey, type ApiClient } from '../api';
import {
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  MutationMessage,
  PageHeader,
  StatusBadge,
  SubmitButton,
} from '../components';
import { formText } from '../form';
import { formatDateTime, parseJsonObject, parseMajorMoney, shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type { ManualReview } from '../types';

const RESOLUTIONS = [
  'FULL_REFUND',
  'PARTIAL_REFUND',
  'REMAKE',
  'SUBSTITUTION',
  'MANUALLY_FULFILLED',
  'NO_FINANCIAL_ACTION',
];

export function ReviewsPage({
  api,
  canResolve,
  currentUserId,
}: {
  api: ApiClient;
  canResolve: boolean;
  currentUserId: string;
}) {
  const loader = useCallback(() => api.get<ManualReview[]>('/admin/reviews?limit=200'), [api]);
  const resource = useAsyncResource(loader);
  const [selected, setSelected] = useState<ManualReview | null>(null);
  const [pending, setPending] = useState(false);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const resolutionKey = useRef<{ reviewId: string; version: number; key: string } | null>(null);

  const replace = (updated: ManualReview) => {
    resource.setData(
      (current) => current?.map((entry) => (entry.id === updated.id ? updated : entry)) ?? null,
    );
    setSelected(updated);
  };
  const assignToMe = (review: ManualReview) => {
    setMutationError(null);
    setSuccess(null);
    void api
      .post<ManualReview>(`/admin/reviews/${review.id}/assign`, {
        expected_version: review.version,
        assignee_user_id: currentUserId,
      })
      .then((updated) => {
        replace(updated);
        setSuccess(`Case ${updated.case_number} assigned.`);
      }, setMutationError);
  };
  const resolve = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    const form = event.currentTarget;
    const resolution = formText(form, 'resolution');
    const refundText = formText(form, 'refund_amount');
    setPending(true);
    setMutationError(null);
    setSuccess(null);
    let payload: Record<string, unknown>;
    let refundAmount: number | null;
    try {
      payload = parseJsonObject(formText(form, 'payload'), 'Payload');
      refundAmount = resolution === 'PARTIAL_REFUND' ? parseMajorMoney(refundText) : null;
    } catch (error) {
      setPending(false);
      setMutationError(error);
      return;
    }
    void api
      .post<ManualReview>(
        `/admin/reviews/${selected.id}/resolve`,
        {
          expected_version: selected.version,
          resolution,
          refund_amount_minor: refundAmount,
          notes: formText(form, 'notes'),
          payload,
        },
        {
          'Idempotency-Key': (() => {
            const current = resolutionKey.current;
            if (current?.reviewId === selected.id && current.version === selected.version) {
              return current.key;
            }
            const key = createIdempotencyKey('manual-review');
            resolutionKey.current = { reviewId: selected.id, version: selected.version, key };
            return key;
          })(),
        },
      )
      .then(
        (updated) => {
          replace(updated);
          resolutionKey.current = null;
          setPending(false);
          setSuccess(`Case ${updated.case_number} resolved.`);
        },
        (error: unknown) => {
          setPending(false);
          setMutationError(error);
        },
      );
  };

  return (
    <section>
      <PageHeader
        title="Manual review"
        description="Human approval queue for failed fulfillment and financial remediation."
      />
      <MutationMessage error={mutationError} success={success} />
      {resource.loading ? <LoadingState label="Loading manual reviews…" /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState
          title="Review queue is empty"
          detail="There are no manual cases awaiting attention."
        />
      ) : null}
      {resource.data?.length ? (
        <div className="card-grid">
          {resource.data.map((review) => (
            <article className="card" key={review.id}>
              <header className="card-header">
                <div>
                  <h2>{review.case_number}</h2>
                  <p>
                    {review.reason_code} · priority {review.priority}
                  </p>
                </div>
                <StatusBadge value={review.status} />
              </header>
              <dl className="definition-grid">
                <div>
                  <dt>Order</dt>
                  <dd className="monospace">{shortId(review.order_id)}</dd>
                </div>
                <div>
                  <dt>Assigned</dt>
                  <dd>{review.assigned_to ? shortId(review.assigned_to) : 'Unassigned'}</dd>
                </div>
                <div>
                  <dt>Assigned at</dt>
                  <dd>{formatDateTime(review.assigned_at)}</dd>
                </div>
                <div>
                  <dt>Version</dt>
                  <dd>{review.version}</dd>
                </div>
              </dl>
              {canResolve && !['RESOLVED', 'CLOSED'].includes(review.status) ? (
                <div className="button-row">
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => assignToMe(review)}
                  >
                    Assign to me
                  </button>
                  <button
                    type="button"
                    className="button button-primary"
                    onClick={() => setSelected(review)}
                  >
                    Resolve
                  </button>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}
      {selected ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="resolve-title"
          >
            <header className="card-header">
              <div>
                <h2 id="resolve-title">Resolve {selected.case_number}</h2>
                <p>Version {selected.version}. This operation is idempotent and audited.</p>
              </div>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => {
                  resolutionKey.current = null;
                  setSelected(null);
                }}
              >
                Close
              </button>
            </header>
            <form className="form-stack" onSubmit={resolve}>
              <Field label="Resolution" htmlFor="resolution">
                <select id="resolution" name="resolution" required defaultValue="FULL_REFUND">
                  {RESOLUTIONS.map((value) => (
                    <option
                      key={value}
                      value={value}
                      disabled={
                        !selected.fulfillment_ticket_id &&
                        ['REMAKE', 'SUBSTITUTION'].includes(value)
                      }
                    >
                      {value.replaceAll('_', ' ')}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label="Partial refund amount (EUR)"
                htmlFor="refund_amount"
                hint="Only used when PARTIAL_REFUND is selected."
              >
                <input
                  id="refund_amount"
                  name="refund_amount"
                  inputMode="decimal"
                  placeholder="0.00"
                />
              </Field>
              <Field label="Notes" htmlFor="notes">
                <textarea id="notes" name="notes" maxLength={2000} rows={4} />
              </Field>
              <Field
                label="Structured payload"
                htmlFor="payload"
                hint="JSON object; use for approved substitution or remake details."
              >
                <textarea id="payload" name="payload" rows={5} defaultValue="{}" />
              </Field>
              <SubmitButton pending={pending}>Confirm resolution</SubmitButton>
            </form>
          </section>
        </div>
      ) : null}
    </section>
  );
}
