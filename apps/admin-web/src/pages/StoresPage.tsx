import { useCallback, useEffect, useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
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
import { formChecked, formNumber } from '../form';
import { useAsyncResource } from '../hooks';
import type { StorePolicy, StoreWithPolicy } from '../types';

export function StoresPage({ api, canWrite }: { api: ApiClient; canWrite: boolean }) {
  const loader = useCallback(() => api.get<StoreWithPolicy[]>('/admin/organization/stores'), [api]);
  const resource = useAsyncResource(loader);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedId && resource.data?.[0]) {
      setSelectedId(resource.data[0].store.id);
    }
  }, [resource.data, selectedId]);

  const selected = resource.data?.find((entry) => entry.store.id === selectedId) ?? null;
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    setPending(true);
    setMutationError(null);
    setSuccess(null);
    const form = event.currentTarget;
    void api
      .patch<StorePolicy>(`/admin/organization/stores/${selected.store.id}/policy`, {
        accepting_orders: formChecked(form, 'accepting_orders'),
        max_open_tickets: formNumber(form, 'max_open_tickets'),
        kds_heartbeat_seconds: formNumber(form, 'kds_heartbeat_seconds'),
        printer_fallback_enabled: formChecked(form, 'printer_fallback_enabled'),
        expected_version: selected.policy.version,
      })
      .then(
        (policy) => {
          resource.setData(
            (current) =>
              current?.map((entry) =>
                entry.store.id === selected.store.id ? { ...entry, policy } : entry,
              ) ?? null,
          );
          setPending(false);
          setSuccess('Store policy updated.');
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
        title="Stores and operating policy"
        description="View assigned stores and control whether kiosks may accept orders."
      />
      {resource.loading ? <LoadingState label="Loading stores…" /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState title="No stores" detail="No active store is assigned to this account." />
      ) : null}
      {resource.data && resource.data.length > 0 ? (
        <div className="split-layout">
          <aside className="selection-list" aria-label="Assigned stores">
            {resource.data.map((entry) => (
              <button
                type="button"
                key={entry.store.id}
                className={entry.store.id === selectedId ? 'selected' : ''}
                onClick={() => setSelectedId(entry.store.id)}
              >
                <strong>{entry.store.name}</strong>
                <span>{entry.store.code}</span>
                <StatusBadge value={entry.policy.accepting_orders} />
              </button>
            ))}
          </aside>
          {selected ? (
            <article className="card">
              <header className="card-header">
                <div>
                  <h2>{selected.store.name}</h2>
                  <p>
                    {selected.store.country_code} · {selected.store.currency} ·{' '}
                    {selected.store.locale}
                  </p>
                </div>
                <StatusBadge value={selected.store.active} />
              </header>
              <dl className="definition-grid">
                <div>
                  <dt>Store ID</dt>
                  <dd className="monospace">{selected.store.id}</dd>
                </div>
                <div>
                  <dt>Time zone</dt>
                  <dd>{selected.store.timezone}</dd>
                </div>
                <div>
                  <dt>Policy version</dt>
                  <dd>{selected.policy.version}</dd>
                </div>
              </dl>
              <MutationMessage error={mutationError} success={success} />
              <form
                key={`${selected.store.id}-${selected.policy.version}`}
                className="form-grid"
                onSubmit={submit}
              >
                <label className="check-field">
                  <input
                    type="checkbox"
                    name="accepting_orders"
                    defaultChecked={selected.policy.accepting_orders}
                    disabled={!canWrite}
                  />{' '}
                  Accepting orders
                </label>
                <Field label="Maximum open tickets" htmlFor="max_open_tickets">
                  <input
                    id="max_open_tickets"
                    name="max_open_tickets"
                    type="number"
                    min="1"
                    max="1000"
                    defaultValue={selected.policy.max_open_tickets}
                    disabled={!canWrite}
                    required
                  />
                </Field>
                <Field label="KDS heartbeat seconds" htmlFor="kds_heartbeat_seconds">
                  <input
                    id="kds_heartbeat_seconds"
                    name="kds_heartbeat_seconds"
                    type="number"
                    min="5"
                    max="300"
                    defaultValue={selected.policy.kds_heartbeat_seconds}
                    disabled={!canWrite}
                    required
                  />
                </Field>
                <label className="check-field">
                  <input
                    type="checkbox"
                    name="printer_fallback_enabled"
                    defaultChecked={selected.policy.printer_fallback_enabled}
                    disabled={!canWrite}
                  />{' '}
                  Printer fallback enabled
                </label>
                {canWrite ? (
                  <SubmitButton pending={pending}>Save policy</SubmitButton>
                ) : (
                  <p className="muted">Read-only: organization:write permission is required.</p>
                )}
              </form>
            </article>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
