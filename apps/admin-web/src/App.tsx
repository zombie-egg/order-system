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
import { AdminI18nProvider, LanguageSwitch, useAdminI18n } from './i18n';
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
  label: 'dashboard' | 'stores' | 'users' | 'catalog' | 'orders' | 'refunds' | 'reviews' | 'reports' | 'audit';
  permissions: string[];
}
const NAVIGATION: NavItem[] = [
  { id: 'dashboard', label: 'dashboard', permissions: ['report:read'] },
  { id: 'stores', label: 'stores', permissions: ['organization:read'] },
  { id: 'users', label: 'users', permissions: ['identity:read'] },
  {
    id: 'catalog',
    label: 'catalog',
    permissions: ['catalog:read', 'catalog:write', 'catalog:tenant_write'],
  },
  { id: 'orders', label: 'orders', permissions: ['order:read'] },
  { id: 'refunds', label: 'refunds', permissions: ['payment:read'] },
  { id: 'reviews', label: 'reviews', permissions: ['review:read'] },
  { id: 'reports', label: 'reports', permissions: ['report:read'] },
  { id: 'audit', label: 'audit', permissions: ['audit:read'] },
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

function AdminApp() {
  const { t, choose } = useAdminI18n();
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
          clearSession(choose('登录已过期或无效，请重新登录。', 'De sessie is verlopen of ongeldig. Log opnieuw in.')),
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
        if (active) clearSession(choose('无法恢复已保存的登录会话。', 'De opgeslagen sessie kan niet worden hersteld.'));
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
      clearSession(choose('登录已过期，请重新登录。', 'De sessie is verlopen. Log opnieuw in.'));
      return;
    }
    const timeout = window.setTimeout(
      () => clearSession(choose('登录已过期，请重新登录。', 'De sessie is verlopen. Log opnieuw in.')),
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
        throw new Error(choose('API 返回的访问令牌已过期。', 'De API gaf een verlopen toegangstoken terug.'));
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
        <LoadingState label={choose('正在恢复员工登录会话…', 'Medewerkerssessie herstellen…')} />
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
        {t('skip')}
      </a>
      <aside className="sidebar">
        <header>
          <p className="eyebrow">SipPilot · 饮航</p>
          <strong>{t('admin')}</strong>
          <span>{t('operations')}</span>
          <LanguageSwitch />
        </header>
        <nav aria-label={choose('主导航', 'Hoofdnavigatie')}>
          {availableNavigation.map((item) => (
            <button
              key={item.id}
              type="button"
              className={activePage === item.id ? 'active' : ''}
              aria-current={activePage === item.id ? 'page' : undefined}
              onClick={() => setPage(item.id)}
            >
              {t(item.label)}
            </button>
          ))}
        </nav>
        <footer>
          <span>{choose('租户', 'Tenant')}</span>
          <code>{principal.tenant_id.slice(0, 12)}…</code>
          <span>
            {choose(`已分配 ${principal.store_ids.length} 家门店`, `${principal.store_ids.length} toegewezen vestiging(en)`)}
          </span>
          <button type="button" className="button button-secondary" onClick={() => clearSession()}>
            {t('signOut')}
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
            {choose('此账号没有管理后台权限。请联系所有者分配门店角色。', 'Dit account heeft geen rechten voor de beheeromgeving. Vraag een eigenaar om een vestigingsrol toe te wijzen.')}
          </Notice>
        ) : null}
      </main>
    </div>
  );
}

export function App() {
  return (
    <AdminI18nProvider>
      <AdminApp />
    </AdminI18nProvider>
  );
}
