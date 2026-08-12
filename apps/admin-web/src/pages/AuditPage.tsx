import { useCallback, useState } from 'react';
import type { ApiClient } from '../api';
import { EmptyState, ErrorState, LoadingState, PageHeader, StatusBadge } from '../components';
import { formatDateTime, shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type { AuditLog } from '../types';

export function AuditPage({ api }: { api: ApiClient }) {
  const loader = useCallback(() => api.get<AuditLog[]>('/admin/audit?limit=200'), [api]);
  const resource = useAsyncResource(loader);
  const [expanded, setExpanded] = useState<string | null>(null);

  return (
    <section>
      <PageHeader
        title="Audit log"
        description="Immutable operational and administrative activity visible to your store scope."
        actions={
          <button type="button" className="button button-secondary" onClick={resource.reload}>
            Refresh
          </button>
        }
      />
      {resource.loading ? <LoadingState label="Loading audit log…" /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState title="No audit entries" detail="No visible audit records have been written." />
      ) : null}
      {resource.data?.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Target</th>
                <th>Store</th>
                <th>Detail</th>
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
                  <td className="monospace">{log.store_id ? shortId(log.store_id) : 'Tenant'}</td>
                  <td>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => setExpanded(expanded === log.id ? null : log.id)}
                      aria-expanded={expanded === log.id}
                    >
                      {expanded === log.id ? 'Hide' : 'View'}
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
