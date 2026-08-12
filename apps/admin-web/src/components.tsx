import { cloneElement, isValidElement, type ReactElement, type ReactNode } from 'react';
import { ApiError, errorMessage } from './api';

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="state-panel" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }) {
  const headingId = `empty-${toDomId(title)}`;
  return (
    <section className="state-panel" aria-labelledby={headingId}>
      <div>
        <h2 id={headingId}>{title}</h2>
        <p>{detail}</p>
      </div>
    </section>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <section className="notice notice-error" role="alert">
      <div>
        <strong>Request failed</strong>
        <p>{errorMessage(error)}</p>
        {error instanceof ApiError && error.status === 403 ? (
          <p>Your account does not have permission for this operation.</p>
        ) : null}
      </div>
      {retry ? (
        <button type="button" className="button button-secondary" onClick={retry}>
          Try again
        </button>
      ) : null}
    </section>
  );
}

export function Notice({
  kind = 'success',
  children,
}: {
  kind?: 'success' | 'warning' | 'info';
  children: ReactNode;
}) {
  return (
    <div className={`notice notice-${kind}`} role="status" aria-live="polite">
      {children}
    </div>
  );
}

export function StatusBadge({ value }: { value: string | boolean }) {
  const label = typeof value === 'boolean' ? (value ? 'Enabled' : 'Disabled') : value;
  const state = label.toLowerCase().replaceAll('_', '-');
  return <span className={`status-badge status-${state}`}>{label.replaceAll('_', ' ')}</span>;
}

export function Field({
  label,
  htmlFor,
  hint,
  children,
}: {
  label: string;
  htmlFor: string;
  hint?: string;
  children: ReactNode;
}) {
  const hintId = hint ? `${htmlFor}-hint` : undefined;
  const control =
    hintId && isValidElement(children)
      ? cloneElement(children as ReactElement<{ 'aria-describedby'?: string }>, {
          'aria-describedby': hintId,
        })
      : children;
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {control}
      {hint ? <small id={hintId}>{hint}</small> : null}
    </div>
  );
}

export function SubmitButton({ pending, children }: { pending: boolean; children: ReactNode }) {
  return (
    <button type="submit" className="button button-primary" disabled={pending}>
      {pending ? 'Saving…' : children}
    </button>
  );
}

export function MutationMessage({ error, success }: { error: unknown; success: string | null }) {
  if (error) {
    return <ErrorState error={error} />;
  }
  if (success) {
    return <Notice>{success}</Notice>;
  }
  return null;
}

function toDomId(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/gu, '-')
    .replace(/^-|-$/gu, '');
}
