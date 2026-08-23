import { cloneElement, isValidElement, type ReactElement, type ReactNode } from 'react';
import { ApiError, errorMessage } from './api';
import { useAdminI18n } from './i18n';

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

export function LoadingState({ label = '正在加载…' }: { label?: string }) {
  const { t } = useAdminI18n();
  return (
    <div className="state-panel" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label === '正在加载…' ? t('loading') : label}</span>
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
  const { t, choose } = useAdminI18n();
  return (
    <section className="notice notice-error" role="alert">
      <div>
        <strong>{choose('请求失败', 'Verzoek mislukt')}</strong>
        <p>{errorMessage(error)}</p>
        {error instanceof ApiError && error.status === 403 ? (
          <p>{choose('当前账号没有执行此操作的权限。', 'Dit account heeft geen toestemming voor deze actie.')}</p>
        ) : null}
      </div>
      {retry ? (
        <button type="button" className="button button-secondary" onClick={retry}>
          {t('retry')}
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
  const { language } = useAdminI18n();
  const raw = typeof value === 'boolean' ? (value ? 'ENABLED' : 'DISABLED') : value;
  const labels: Record<string, [string, string]> = {
    ENABLED: ['已启用', 'Ingeschakeld'], DISABLED: ['已停用', 'Uitgeschakeld'], ACTIVE: ['启用', 'Actief'], INACTIVE: ['停用', 'Inactief'],
    PENDING: ['待处理', 'In afwachting'], PAID: ['已支付', 'Betaald'], REFUNDED: ['已退款', 'Terugbetaald'], FAILED: ['失败', 'Mislukt'],
    OPEN: ['开放', 'Open'], RESOLVED: ['已处理', 'Afgehandeld'], CLOSED: ['已关闭', 'Gesloten'], QUEUED: ['排队中', 'In wachtrij'], PREPARING: ['制作中', 'In bereiding'], READY: ['待取餐', 'Klaar'],
    ACKNOWLEDGED: ['已确认', 'Bevestigd'], COLLECTED: ['已取餐', 'Opgehaald'], ON_HOLD: ['已暂停', 'In wachtstand'], UNFULFILLABLE: ['无法履约', 'Niet uitvoerbaar'], CANCELLED: ['已取消', 'Geannuleerd'],
    PROCESSING: ['处理中', 'In verwerking'], SUCCEEDED: ['成功', 'Geslaagd'], EXECUTED: ['已执行', 'Uitgevoerd'], UNKNOWN: ['未知', 'Onbekend'],
  };
  const label = labels[raw]?.[language === 'zh-CN' ? 0 : 1] ?? raw.replaceAll('_', ' ');
  const state = raw.toLowerCase().replaceAll('_', '-');
  return <span className={`status-badge status-${state}`}>{label}</span>;
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
  const { t } = useAdminI18n();
  return (
    <button type="submit" className="button button-primary" disabled={pending}>
      {pending ? t('saving') : children}
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
