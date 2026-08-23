import { useCallback, useState } from 'react';
import type { ApiClient } from '../api';
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components';
import { formatDateTime, shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type { AuditLog } from '../types';
import { useAdminI18n } from '../i18n';

export function AuditPage({ api }: { api: ApiClient }) {
  const { t, choose } = useAdminI18n();
  const loader = useCallback(() => api.get<AuditLog[]>('/admin/audit?limit=200'), [api]);
  const resource = useAsyncResource(loader);
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <section>
      <PageHeader
        title={t('audit')}
        description={choose('查看当前门店范围内不可篡改的运营与后台操作记录。', 'Bekijk onveranderbare operationele en beheeracties binnen het bereik van je vestigingen.')}
        actions={
          <button type="button" className="button button-secondary" onClick={resource.reload}>
            {t('refresh')}
          </button>
        }
      />
      {resource.loading ? <LoadingState label={choose('正在加载审计记录…', 'Auditlog laden…')} /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState title={choose('暂无审计记录', 'Geen auditregels')} detail={choose('当前没有可查看的审计记录。', 'Er zijn geen zichtbare auditregels.')} />
      ) : null}
      {resource.data?.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{t('time')}</th><th>{choose('操作主体', 'Actor')}</th><th>{t('action')}</th><th>{choose('对象', 'Doel')}</th><th>{t('store')}</th><th>{t('detail')}</th>
              </tr>
            </thead>
            <tbody>
              {resource.data.map((log) => (
                <tr key={log.id}>
                  <td>{formatDateTime(log.occurred_at)}</td>
                  <td>
                    <StatusBadge value={log.actor_type} />
                    <br />
                    <span className="muted monospace">
                      {shortId(log.actor_user_id ?? log.actor_device_id ?? 'system')}
                    </span>
                  </td>
                  <td>{log.action}</td>
                  <td>
                    {log.target_type}
                    <br />
                    <span className="muted monospace">{shortId(log.target_id)}</span>
                  </td>
                  <td className="monospace">{log.store_id ? shortId(log.store_id) : choose('租户', 'Tenant')}</td>
                  <td>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => setExpanded(expanded === log.id ? null : log.id)}
                      aria-expanded={expanded === log.id}
                    >
                      {expanded === log.id ? t('hide') : t('view')}
                    </button>
                    {expanded === log.id ? (
                      <pre className="json-view">
                        {JSON.stringify(
                          {
                            before: log.before,
                            after: log.after,
                            metadata: log.metadata,
                            correlation_id: log.correlation_id,
                          },
                          null,
                          2,
                        )}
                      </pre>
                    ) : null}
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
