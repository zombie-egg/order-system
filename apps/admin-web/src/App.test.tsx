import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';

const principal = {
  user_id: 'user-1',
  tenant_id: 'tenant-1',
  permissions: ['report:read', 'organization:read'],
  store_ids: ['store-1'],
};

const ownerPrincipal = {
  user_id: 'owner-1',
  tenant_id: 'tenant-1',
  permissions: [
    'organization:read',
    'organization:write',
    'identity:read',
    'identity:write',
    'catalog:read',
    'catalog:write',
    'catalog:tenant_write',
    'order:read',
    'payment:read',
    'payment:reconcile',
    'review:read',
    'review:resolve',
    'report:read',
    'audit:read',
  ],
  store_ids: ['store-1'],
};

describe('Admin console', () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url =
          typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
        if (url.endsWith('/auth/token')) {
          return json({
            access_token: 'token',
            token_type: 'bearer',
            expires_at: '2099-01-01T00:00:00Z',
          });
        }
        if (url.endsWith('/auth/me')) return json(principal);
        if (url.includes('/reports/operations')) {
          return json([
            {
              store_id: 'store-1',
              open_orders: 2,
              open_tickets: 1,
              open_manual_reviews: 0,
              unknown_payments: 0,
              paid_orders_without_tickets: 0,
              pending_outbox_events: 0,
            },
          ]);
        }
        return json([]);
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('authenticates and renders permission-scoped navigation', async () => {
    render(<App />);
    expect(screen.getByRole('heading', { name: '员工登录' })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('租户代码'), { target: { value: 'demo' } });
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('密码'), {
      target: { value: 'correct horse battery staple' },
    });
    fireEvent.click(screen.getByRole('button', { name: '员工登录' }));
    expect(await screen.findByText('管理后台')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '经营概览' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: '退款' })).not.toBeInTheDocument();
    expect(sessionStorage.getItem('smart-drink-admin-session')).not.toContain('correct horse');
  });

  it('shows the server problem and remains on the login boundary', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => json({ detail: 'Sign-in failed.' }, 401)),
    );
    render(<App />);
    fireEvent.change(screen.getByLabelText('租户代码'), { target: { value: 'demo' } });
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'wrong password' } });
    fireEvent.click(screen.getByRole('button', { name: '员工登录' }));
    expect(await screen.findByText('Sign-in failed.')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: '员工登录' })).toBeInTheDocument();
  });

  it('does not persist a token when principal loading fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url =
          typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
        if (url.endsWith('/auth/token')) {
          return json({
            access_token: 'token-that-must-not-persist',
            token_type: 'bearer',
            expires_at: '2099-01-01T00:00:00Z',
          });
        }
        return json({ detail: 'The signed-in account is unavailable.' }, 401);
      }),
    );
    render(<App />);
    fireEvent.change(screen.getByLabelText('租户代码'), { target: { value: 'demo' } });
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'admin' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'valid password' } });
    fireEvent.click(screen.getByRole('button', { name: '员工登录' }));
    expect(await screen.findByText('The signed-in account is unavailable.')).toBeInTheDocument();
    expect(sessionStorage.getItem('smart-drink-admin-session')).toBeNull();
  });

  it('restores a valid saved session without posting another password', async () => {
    sessionStorage.setItem(
      'smart-drink-admin-session',
      JSON.stringify({
        accessToken: 'saved-token',
        apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
        expiresAt: '2099-01-01T00:00:00Z',
        refreshToken: 'saved-refresh-token',
      }),
    );
    const fetchMock = vi.mocked(fetch);
    render(<App />);
    expect(await screen.findByText('管理后台')).toBeInTheDocument();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(
      fetchMock.mock.calls.some(([input]) => {
        const url =
          typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
        return url.endsWith('/auth/token');
      }),
    ).toBe(false);
  });

  it('uses backend role codes when creating a staff account', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith('/auth/token')) {
        return json({
          access_token: 'owner-token',
          token_type: 'bearer',
          expires_at: '2099-01-01T00:00:00Z',
        });
      }
      if (url.endsWith('/auth/me')) return json(ownerPrincipal);
      if (url.endsWith('/admin/organization/stores')) {
        return json([
          {
            store: {
              id: 'store-1',
              code: 'AMS-01',
              name: 'Amsterdam Demo',
              country_code: 'NL',
              currency: 'EUR',
              locale: 'nl-NL',
              timezone: 'Europe/Amsterdam',
              active: true,
              version: 1,
            },
            policy: {
              store_id: 'store-1',
              accepting_orders: true,
              max_open_tickets: 50,
              kds_heartbeat_seconds: 30,
              printer_fallback_enabled: false,
              takeaway_fee_enabled: false,
              takeaway_fee_minor: 0,
              version: 1,
            },
          },
        ]);
      }
      if (url.endsWith('/admin/users') && init?.method === 'POST') {
        return json(
          {
            id: 'user-2',
            tenant_id: 'tenant-1',
            username: 'new-staff',
            display_name: 'New Staff',
            active: true,
            token_version: 1,
            version: 1,
            last_login_at: null,
            created_at: '2026-08-12T00:00:00Z',
            updated_at: '2026-08-12T00:00:00Z',
          },
          201,
        );
      }
      return json([]);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.change(screen.getByLabelText('租户代码'), { target: { value: 'demo-nl' } });
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'demo-owner' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'owner password' } });
    fireEvent.click(screen.getByRole('button', { name: '员工登录' }));
    await screen.findByText('管理后台');
    fireEvent.click(screen.getByRole('button', { name: '员工' }));
    fireEvent.click(screen.getByText('创建员工账号'));
    fireEvent.change(screen.getByLabelText('门店'), { target: { value: 'store-1' } });
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'new-staff' } });
    fireEvent.change(screen.getByLabelText('显示名称'), { target: { value: 'New Staff' } });
    fireEvent.change(screen.getByLabelText('临时密码'), {
      target: { value: 'temporary-password' },
    });
    fireEvent.change(screen.getByLabelText('角色'), { target: { value: 'reviewer' } });
    fireEvent.click(screen.getByRole('button', { name: '创建员工' }));
    expect(await screen.findByText('员工 new-staff 已创建。')).toBeInTheDocument();
    const createCall = fetchMock.mock.calls.find(([input, init]) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      return url.endsWith('/admin/users') && init?.method === 'POST';
    });
    expect(createCall).toBeDefined();
    const createBody = createCall?.[1]?.body;
    expect(typeof createBody).toBe('string');
    expect(JSON.parse(typeof createBody === 'string' ? createBody : '')).toMatchObject({
      store_id: 'store-1',
      role_codes: ['reviewer'],
    });
  });

  it('does not call a protected page when the account has no admin permissions', async () => {
    const noAccessPrincipal = {
      user_id: 'limited-1',
      tenant_id: 'tenant-1',
      permissions: [],
      store_ids: [],
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (url.endsWith('/auth/token')) {
        return json({
          access_token: 'limited-token',
          token_type: 'bearer',
          expires_at: '2099-01-01T00:00:00Z',
        });
      }
      if (url.endsWith('/auth/me')) return json(noAccessPrincipal);
      return json([], 403);
    });
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);
    fireEvent.change(screen.getByLabelText('租户代码'), { target: { value: 'demo-nl' } });
    fireEvent.change(screen.getByLabelText('用户名'), { target: { value: 'limited' } });
    fireEvent.change(screen.getByLabelText('密码'), { target: { value: 'limited password' } });
    fireEvent.click(screen.getByRole('button', { name: '员工登录' }));
    expect(await screen.findByText(/没有管理后台权限/u)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

function json(body: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}
