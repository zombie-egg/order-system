import { useCallback, useEffect, useMemo, useState } from 'react';
import { BarChart3, Building2, ClipboardList, FileText, LayoutDashboard, Menu, PackagePlus, Palette, ReceiptText, Search, Settings2, ShieldCheck, Store, Users } from 'lucide-react';
import { ApiError, configuredDefaultApiUrl, createApiClient, normalizeApiBaseUrl } from './api';
import { LoadingState, Notice } from './components';
import { AuditPage } from './pages/AuditPage';
import { BrandingPage } from './pages/BrandingPage';
import { DashboardPage } from './pages/DashboardPage';
import { LoginPage, type LoginValues } from './pages/LoginPage';
import { OrdersPage } from './pages/OrdersPage';
import { ProductAddPage } from './pages/ProductAddPage';
import { ProductsPricingPage } from './pages/ProductsPricingPage';
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
  | 'branding'
  | 'product-add'
  | 'catalog'
  | 'orders'
  | 'refunds'
  | 'reviews'
  | 'reports'
  | 'audit';
interface NavItem {
  id: PageId;
  label: 'dashboard' | 'stores' | 'users' | 'branding' | 'productAdd' | 'catalog' | 'orders' | 'refunds' | 'reviews' | 'reports' | 'audit';
  permissions: string[];
}
const NAVIGATION: NavItem[] = [
  { id: 'dashboard', label: 'dashboard', permissions: ['report:read'] },
  { id: 'stores', label: 'stores', permissions: ['organization:read'] },
  { id: 'users', label: 'users', permissions: ['identity:read'] },
  { id: 'branding', label: 'branding', permissions: ['organization:write', 'catalog:tenant_write'] },
  {
    id: 'product-add',
    label: 'productAdd',
    permissions: ['catalog:write', 'catalog:tenant_write'],
  },
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

function NavIcon({ id }: { id: PageId }) {
  const icons = { dashboard: LayoutDashboard, stores: Store, users: Users, branding: Palette, 'product-add': PackagePlus, catalog: ClipboardList, orders: ReceiptText, refunds: FileText, reviews: ShieldCheck, reports: BarChart3, audit: Settings2 };
  const Icon = icons[id];
  return <Icon aria-hidden="true" size={16} strokeWidth={1.8} />;
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
      typeof candidate.refreshToken !== 'string' ||
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
      refreshToken: candidate.refreshToken,
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
  const [navigationSearch, setNavigationSearch] = useState('');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  const clearSession = useCallback((message?: string) => {
    sessionStorage.removeItem(SESSION_KEY);
    setSession(null);
    setPrincipal(null);
    setStores([]);
    setAuthLoading(false);
    setSessionMessage(message ?? null);
  }, []);
  // Silently renew the short-lived access token using the persisted refresh token.
  const refreshSession = useCallback(async (): Promise<StoredSession | null> => {
    if (!session || !session.refreshToken) return null;
    const client = createApiClient({
      apiBaseUrl: session.apiBaseUrl,
      getAccessToken: () => null,
      onUnauthorized: () => undefined,
    });
    try {
      const token = await client.request<AccessTokenResponse>('/auth/refresh', {
        method: 'POST',
        authenticated: false,
        body: { refresh_token: session.refreshToken },
      });
      const next: StoredSession = {
        apiBaseUrl: session.apiBaseUrl,
        accessToken: token.access_token,
        expiresAt: token.expires_at,
        refreshToken: token.refresh_token ?? session.refreshToken,
      };
      sessionStorage.setItem(SESSION_KEY, JSON.stringify(next));
      setSession(next);
      return next;
    } catch {
      return null;
    }
  }, [session]);
  const api = useMemo(
    () =>
      createApiClient({
        apiBaseUrl: session?.apiBaseUrl ?? configuredDefaultApiUrl,
        getAccessToken: () => session?.accessToken ?? null,
        onUnauthorized: () =>
          clearSession(choose('登录已过期或无效，请重新登录。', 'De sessie is verlopen of ongeldig. Log opnieuw in.')),
        refresh: session
          ? async () => (await refreshSession())?.accessToken ?? null
          : undefined,
      }),
    [choose, clearSession, session, refreshSession],
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
    const restore = async () => {
      // If the saved access token is already close to expiring (e.g. the tab was
      // suspended or closed for a while), renew it silently before loading identity.
      let target = session;
      if (Date.parse(session.expiresAt) <= Date.now() + 60_000) {
        const renewed = await refreshSession();
        if (!renewed) {
          if (active) {
            clearSession(choose('登录已过期，请重新登录。', 'De sessie is verlopen. Log opnieuw in.'));
          }
          return;
        }
        target = renewed;
      }
      try {
        const identity = await loadIdentity(target);
        if (active) activateIdentity(identity);
      } catch {
        if (active) {
          clearSession(choose('无法恢复已保存的登录会话。', 'De opgeslagen sessie kan niet worden hersteld.'));
        }
      }
    };
    void restore();
    return () => {
      active = false;
    };
  }, [activateIdentity, choose, clearSession, loadIdentity, principal, refreshSession, session]);
  useEffect(() => {
    if (!session) return;
    const expiryTime = Date.parse(session.expiresAt);
    if (!Number.isFinite(expiryTime) || expiryTime <= Date.now()) {
      clearSession(choose('登录已过期，请重新登录。', 'De sessie is verlopen. Log opnieuw in.'));
      return;
    }
    // Proactively renew the access token a few minutes before it expires so an
    // actively used session never logs the user out mid-work.
    const refreshIn = Math.min(
      2_147_483_647,
      Math.max(30_000, expiryTime - Date.now() - 5 * 60_000),
    );
    const timer = window.setTimeout(() => {
      void refreshSession();
    }, refreshIn);
    return () => window.clearTimeout(timer);
  }, [choose, clearSession, refreshSession, session]);

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
    const next: StoredSession = {
      apiBaseUrl: values.apiBaseUrl,
      accessToken: token.access_token,
      expiresAt: token.expires_at,
      refreshToken: token.refresh_token ?? '',
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
  // Only the tenant owner (who holds catalog:tenant_write) may add stores or edit
  // tenant-wide branding; store-scoped managers keep their own-store operations.
  const isOwner = permissions.has('catalog:tenant_write');
  const availableNavigation = NAVIGATION.filter((item) => canOpen(item, permissions));
  const activePage = availableNavigation.some((item) => item.id === page)
    ? page
    : (availableNavigation[0]?.id ?? null);
  const matchingNavigation = availableNavigation.filter((item) =>
    t(item.label).toLocaleLowerCase().includes(navigationSearch.trim().toLocaleLowerCase()),
  );
  return (
    <div className={`app-shell${sidebarCollapsed ? ' sidebar-collapsed' : ''}`}>
      <a href="#main-content" className="skip-link">
        {t('skip')}
      </a>
      <aside className="sidebar">
        <header>
          <div className="sidebar-brand-row"><span className="sidebar-brand-mark">SP</span><div><strong>SipPilot</strong><span>{t('admin')}</span></div></div>
          <LanguageSwitch />
        </header>
        <nav aria-label={choose('主导航', 'Hoofdnavigatie')}>
          <span className="sidebar-section-label">{choose('概览', 'Algemeen')}</span>
          {availableNavigation.filter((item) => ['dashboard', 'orders'].includes(item.id)).map((item) => (
            <button
              key={item.id}
              type="button"
              className={activePage === item.id ? 'active' : ''}
              aria-current={activePage === item.id ? 'page' : undefined}
              onClick={() => setPage(item.id)}
            >
              <NavIcon id={item.id} />{t(item.label)}
            </button>
          ))}
          <span className="sidebar-section-label">{choose('运营', 'Operatie')}</span>
          {availableNavigation.filter((item) => ['stores', 'product-add', 'catalog', 'refunds', 'reviews'].includes(item.id)).map((item) => (
            <button key={item.id} type="button" className={activePage === item.id ? 'active' : ''} aria-current={activePage === item.id ? 'page' : undefined} onClick={() => setPage(item.id)}><NavIcon id={item.id} />{t(item.label)}</button>
          ))}
          <span className="sidebar-section-label">{choose('管理', 'Beheer')}</span>
          {availableNavigation.filter((item) => ['users', 'branding', 'reports', 'audit'].includes(item.id)).map((item) => (
            <button key={item.id} type="button" className={activePage === item.id ? 'active' : ''} aria-current={activePage === item.id ? 'page' : undefined} onClick={() => setPage(item.id)}><NavIcon id={item.id} />{t(item.label)}</button>
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
      <div className="admin-workspace">
      <header className="admin-topbar">
        <button
          className="topbar-icon-button"
          type="button"
          aria-label={choose('收起或展开侧边栏', 'Zijbalk in- of uitklappen')}
          aria-expanded={!sidebarCollapsed}
          onClick={() => setSidebarCollapsed((current) => !current)}
        >
          <Menu size={17} />
        </button>
        <label className="admin-search"><Search size={16} aria-hidden="true" /><input value={navigationSearch} onChange={(event) => setNavigationSearch(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && matchingNavigation[0]) { setPage(matchingNavigation[0].id); setNavigationSearch(''); } }} placeholder={choose('搜索页面…', 'Pagina zoeken…')} /><kbd>⌘ K</kbd></label>
        <div className="topbar-context"><Building2 size={16} aria-hidden="true" /><span>{stores[0]?.store.name ?? choose('未分配门店', 'Geen vestiging')}</span></div>
      </header>
      <main id="main-content" className="main-content" tabIndex={-1}>
        {activePage === 'dashboard' ? (
          <DashboardPage
            api={api}
            canReadOrganization={permissions.has('organization:read')}
            stores={stores}
            assignedStoreIds={principal.store_ids}
          />
        ) : null}
        {activePage === 'stores' ? (
          <StoresPage
            api={api}
            canWrite={permissions.has('organization:write')}
            canAddStore={isOwner}
          />
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
        {activePage === 'branding' ? (
          <BrandingPage api={api} canWrite={permissions.has('organization:write')} />
        ) : null}
        {activePage === 'product-add' ? (
          <ProductAddPage
            api={api}
            stores={stores}
            canWrite={permissions.has('catalog:write')}
          />
        ) : null}
        {activePage === 'catalog' ? (
          <ProductsPricingPage
            api={api}
            stores={stores}
            canWrite={permissions.has('catalog:write')}
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
