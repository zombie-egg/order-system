import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, configuredDefaultApiUrl, createApiClient, normalizeApiBaseUrl } from './api';
import { LoadingState, Notice } from './components';
import { AuditPage } from './pages/AuditPage';
import { CatalogPage } from './pages/CatalogPage';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage, type LoginValues } from './pages/LoginPage';
import { OrdersPage } from './pages/OrdersPage';
import { RefundsPage } from './pages/RefundsPage';
import { ReportsPage } from './pages/ReportsPage';
import { ReviewsPage } from './pages/ReviewsPage';
import { StoresPage } from './pages/StoresPage';
import { UsersPage } from './pages/UsersPage';
import type { AccessTokenResponse, Principal, StoredSession, StoreWithPolicy } from './types';

const SESSION_KEY = 'smart-drink-admin-session';
type PageId =
  | 'dashboard'
  | 'stores'
  | 'users'
  | 'catalog'
  | 'orders'
  | 'refunds'
  | 'reviews'
  | 'reports'
  | 'audit';
interface NavItem {
  id: PageId;
  label: string;
  permissions: string[];
}
const NAVIGATION: NavItem[] = [
  { id: 'dashboard', label: 'Overview', permissions: ['report:read'] },
  { id: 'stores', label: 'Stores', permissions: ['organization:read'] },
  { id: 'users', label: 'Staff', permissions: ['identity:read'] },
  {
    id: 'catalog',
    label: 'Catalog & pricing',
    permissions: ['catalog:read', 'catalog:write', 'catalog:tenant_write'],
  },
  { id: 'orders', label: 'Orders', permissions: ['order:read'] },
  { id: 'refunds', label: 'Refunds', permissions: ['payment:read'] },
  { id: 'reviews', label: 'Manual review', permissions: ['review:read'] },
  { id: 'reports', label: 'Reports', permissions: ['report:read'] },
  { id: 'audit', label: 'Audit', permissions: ['audit:read'] },
];

function canOpen(item: NavItem, permissions: Iterable<string>): boolean {
  const available = permissions instanceof Set ? permissions : new Set(permissions);
  return item.permissions.some((permission) => available.has(permission));
}

function readStoredSession(): StoredSession | null {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const value: unknown = JSON.parse(raw);
    if (!value || typeof value !== 'object') return null;
    const candidate = value as Partial<StoredSession>;
    const expiresAt =
      typeof candidate.expiresAt === 'string' ? Date.parse(candidate.expiresAt) : NaN;
    if (
      typeof candidate.accessToken !== 'string' ||
      typeof candidate.apiBaseUrl !== 'string' ||
      typeof candidate.expiresAt !== 'string' ||
      !Number.isFinite(expiresAt) ||
      expiresAt <= Date.now()
    ) {
      sessionStorage.removeItem(SESSION_KEY);
      return null;
    }
    return {
      accessToken: candidate.accessToken,
      apiBaseUrl: normalizeApiBaseUrl(candidate.apiBaseUrl),
      expiresAt: candidate.expiresAt,
    };
  } catch {
    sessionStorage.removeItem(SESSION_KEY);
    return null;
  }
}

function expiresSoon(expiresAt: string): boolean {
  return Date.parse(expiresAt) <= Date.now() + 15_000;
}

export function App() {
  const initialSession = useMemo(readStoredSession, []);
  const [session, setSession] = useState<StoredSession | null>(initialSession);
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [authLoading, setAuthLoading] = useState(initialSession !== null);
  const [sessionMessage, setSessionMessage] = useState<string | null>(null);
  const [page, setPage] = useState<PageId>('dashboard');
  const [stores, setStores] = useState<StoreWithPolicy[]>([]);

  const clearSession = useCallback((message?: string) => {
    sessionStorage.removeItem(SESSION_KEY);
    setSession(null);
    setPrincipal(null);
    setStores([]);
    setAuthLoading(false);
    setSessionMessage(message ?? null);
  }, []);
  const api = useMemo(
    () =>
      createApiClient({
        apiBaseUrl: session?.apiBaseUrl ?? configuredDefaultApiUrl,
        getAccessToken: () => session?.accessToken ?? null,
        onUnauthorized: () =>
          clearSession('Your session expired or is no longer valid. Please sign in again.'),
      }),
    [clearSession, session],
  );
  const loadIdentity = useCallback(async (activeSession: StoredSession) => {
    const client = createApiClient({
      apiBaseUrl: activeSession.apiBaseUrl,
      getAccessToken: () => activeSession.accessToken,
      onUnauthorized: () => undefined,
    });
    const me = await client.get<Principal>('/auth/me');
    let assignedStores: StoreWithPolicy[] = [];
    if (me.permissions.includes('organization:read')) {
      try {
        assignedStores = await client.get<StoreWithPolicy[]>('/admin/organization/stores');
      } catch (error) {
        if (!(error instanceof ApiError && error.status === 403)) throw error;
      }
    }
    return { me, assignedStores };
  }, []);
  const activateIdentity = useCallback(
    ({ me, assignedStores }: { me: Principal; assignedStores: StoreWithPolicy[] }) => {
      setPrincipal(me);
      setStores(assignedStores);
      const allowed = NAVIGATION.filter((item) => canOpen(item, me.permissions));
      setPage((current) =>
        allowed.some((item) => item.id === current) ? current : (allowed[0]?.id ?? 'dashboard'),
      );
      setAuthLoading(false);
    },
    [],
  );
  useEffect(() => {
    if (!session || principal) return;
    let active = true;
    void loadIdentity(session).then(
      (identity) => {
        if (active) activateIdentity(identity);
      },
      () => {
        if (active) clearSession('The saved session could not be restored.');
      },
    );
    return () => {
      active = false;
    };
  }, [activateIdentity, clearSession, loadIdentity, principal, session]);
  useEffect(() => {
    if (!session) return;
    const expiryTime = Date.parse(session.expiresAt);
    if (!Number.isFinite(expiryTime) || expiresSoon(session.expiresAt)) {
      clearSession('Your session expired. Please sign in again.');
      return;
    }
    const timeout = window.setTimeout(
      () => clearSession('Your session expired. Please sign in again.'),
      Math.min(expiryTime - Date.now(), 2_147_483_647),
    );
    return () => window.clearTimeout(timeout);
  }, [clearSession, session]);

  const login = async (values: LoginValues) => {
    const client = createApiClient({
      apiBaseUrl: values.apiBaseUrl,
      getAccessToken: () => null,
      onUnauthorized: () => undefined,
    });
    const token = await client.request<AccessTokenResponse>('/auth/token', {
      method: 'POST',
      authenticated: false,
      body: {
        tenant_code: values.tenantCode,
        username: values.username,
        password: values.password,
      },
    });
    if (expiresSoon(token.expires_at)) {
      throw new Error('The API returned an already expired access token.');
    }
    const next = {
      apiBaseUrl: values.apiBaseUrl,
      accessToken: token.access_token,
      expiresAt: token.expires_at,
    };
    const identity = await loadIdentity(next);
    sessionStorage.setItem(SESSION_KEY, JSON.stringify(next));
    setSessionMessage(null);
    setSession(next);
    activateIdentity(identity);
  };
  if (!session)
    return (
      <>
        <LoginPage defaultApiUrl={configuredDefaultApiUrl} onLogin={login} />
        {sessionMessage ? (
          <div className="session-message">
            <Notice kind="warning">{sessionMessage}</Notice>
          </div>
        ) : null}
      </>
    );
  if (authLoading || !principal)
    return (
      <main className="centered-page">
        <LoadingState label="Restoring staff session…" />
      </main>
    );
  const permissions = new Set(principal.permissions);
  const availableNavigation = NAVIGATION.filter((item) => canOpen(item, permissions));
  const activePage = availableNavigation.some((item) => item.id === page)
    ? page
    : (availableNavigation[0]?.id ?? null);
  return (
    <div className="app-shell">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <aside className="sidebar">
        <header>
          <p className="eyebrow">SipPilot · 饮航</p>
          <strong>Admin console</strong>
          <span>Store operations platform</span>
        </header>
        <nav aria-label="Primary navigation">
          {availableNavigation.map((item) => (
            <button
              key={item.id}
              type="button"
              className={activePage === item.id ? 'active' : ''}
              aria-current={activePage === item.id ? 'page' : undefined}
              onClick={() => setPage(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <footer>
          <span>Tenant</span>
          <code>{principal.tenant_id.slice(0, 12)}…</code>
          <span>
            {principal.store_ids.length} assigned store{principal.store_ids.length === 1 ? '' : 's'}
          </span>
          <button type="button" className="button button-secondary" onClick={() => clearSession()}>
            Sign out
          </button>
        </footer>
      </aside>
      <main id="main-content" className="main-content" tabIndex={-1}>
        {activePage === 'dashboard' ? (
          <DashboardPage api={api} canReadOrganization={permissions.has('organization:read')} />
        ) : null}
        {activePage === 'stores' ? (
          <StoresPage api={api} canWrite={permissions.has('organization:write')} />
        ) : null}
        {activePage === 'users' ? (
          <UsersPage
            api={api}
            canWrite={permissions.has('identity:write')}
            stores={stores}
            canReadOrganization={permissions.has('organization:read')}
            currentUserId={principal.user_id}
          />
        ) : null}
        {activePage === 'catalog' ? (
          <CatalogPage
            api={api}
            stores={stores}
            assignedStoreIds={principal.store_ids}
            canTenantWrite={permissions.has('catalog:tenant_write')}
            canStoreWrite={permissions.has('catalog:write')}
          />
        ) : null}
        {activePage === 'orders' ? <OrdersPage api={api} /> : null}
        {activePage === 'refunds' ? (
          <RefundsPage
            api={api}
            canResolve={permissions.has('review:resolve')}
            canReconcile={permissions.has('payment:reconcile')}
          />
        ) : null}
        {activePage === 'reviews' ? (
          <ReviewsPage
            api={api}
            canResolve={permissions.has('review:resolve')}
            currentUserId={principal.user_id}
          />
        ) : null}
        {activePage === 'reports' ? (
          <ReportsPage
            api={api}
            stores={stores}
            assignedStoreIds={principal.store_ids}
            canReadOrganization={permissions.has('organization:read')}
          />
        ) : null}
        {activePage === 'audit' ? <AuditPage api={api} /> : null}
        {availableNavigation.length === 0 ? (
          <Notice kind="warning">
            This account has no Admin console permissions. Ask an owner to assign a store role.
          </Notice>
        ) : null}
      </main>
    </div>
  );
}
