import { useCallback, useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
import { STAFF_ROLE_CODES } from '../admin-contracts';
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
import { formatDateTime, shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type { StoreWithPolicy, UserAccount } from '../types';
import { useAdminI18n } from '../i18n';

export function UsersPage({
  api,
  canWrite,
  stores,
  canReadOrganization,
  currentUserId,
}: {
  api: ApiClient;
  canWrite: boolean;
  stores: StoreWithPolicy[];
  canReadOrganization: boolean;
  currentUserId: string;
}) {
  const { t, choose } = useAdminI18n();
  const roleOptions: ReadonlyArray<{ code: (typeof STAFF_ROLE_CODES)[number]; label: string; detail: string }> = [
    { code: 'manager', label: choose('经理', 'Manager'), detail: choose('门店设置、订单、支付、审核、报表和审计。', 'Vestigingsinstellingen, bestellingen, betalingen, beoordelingen, rapportages en audit.') },
    { code: 'staff', label: choose('员工', 'Medewerker'), detail: choose('订单、支付、厨房工作及只读人工审核。', 'Bestellingen, betalingen, keukenwerk en alleen-lezen beoordeling.') },
    { code: 'reviewer', label: choose('审核员', 'Beoordelaar'), detail: choose('订单、支付、人工审核处理和审计。', 'Bestellingen, betalingen, handmatige beoordeling en audit.') },
    { code: 'owner', label: choose('所有者', 'Eigenaar'), detail: choose('所有租户和门店权限，包括员工管理。', 'Alle tenant- en vestigingsrechten, inclusief medewerkersbeheer.') },
  ];
  const loader = useCallback(async () => {
    const users = await api.get<UserAccount[]>('/admin/users');
    return { users };
  }, [api]);
  const resource = useAsyncResource(loader);
  const [pending, setPending] = useState(false);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const createUser = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    setPending(true);
    setMutationError(null);
    setSuccess(null);
    void api
      .post<UserAccount>('/admin/users', {
        store_id: formText(form, 'store_id'),
        username: formText(form, 'username'),
        display_name: formText(form, 'display_name'),
        password: formText(form, 'password'),
        role_codes: formText(form, 'role_codes')
          .split(',')
          .map((value) => value.trim())
          .filter(Boolean),
      })
      .then(
        (user) => {
          resource.setData((current) =>
            current ? { ...current, users: [user, ...current.users] } : current,
          );
          form.reset();
          setPending(false);
          setSuccess(choose(`员工 ${user.username} 已创建。`, `Medewerker ${user.username} is aangemaakt.`));
        },
        (error: unknown) => {
          setPending(false);
          setMutationError(error);
        },
      );
  };

  const toggleStatus = (user: UserAccount) => {
    setMutationError(null);
    setSuccess(null);
    void api
      .patch<UserAccount>(`/admin/users/${user.id}/status`, {
        active: !user.active,
        expected_version: user.version,
      })
      .then((updated) => {
        resource.setData((current) =>
          current
            ? {
                ...current,
                users: current.users.map((entry) => (entry.id === updated.id ? updated : entry)),
              }
            : current,
        );
        setSuccess(choose(`员工 ${updated.username} 已${updated.active ? '启用' : '停用'}。`, `Medewerker ${updated.username} is ${updated.active ? 'geactiveerd' : 'gedeactiveerd'}.`));
      }, setMutationError);
  };

  return (
    <section>
      <PageHeader
        title={t('users')}
        description={choose('租户员工按门店范围与后台角色进行授权。', 'Tenantmedewerkers worden per vestiging en backendrol geautoriseerd.')}
      />
      <MutationMessage error={mutationError} success={success} />
      {canWrite ? (
        <details className="card form-disclosure">
          <summary>{choose('创建员工账号', 'Medewerkersaccount aanmaken')}</summary>
          <form className="form-grid" onSubmit={createUser}>
            <Field label={t('store')} htmlFor="store_id">
              <select id="store_id" name="store_id" required defaultValue="">
                <option value="" disabled>
                  {t('selectStore')}
                </option>
                {stores.map(({ store }) => (
                  <option key={store.id} value={store.id}>
                    {store.name}
                  </option>
                ))}
              </select>
            </Field>
            {!canReadOrganization ? (
              <p className="muted">
                {choose('查看门店名称需要 organization:read 权限，请在创建门店员工前联系所有者授权。', 'Voor vestigingsnamen is organization:read vereist. Vraag een eigenaar om deze machtiging voordat je vestigingsmedewerkers aanmaakt.')}
              </p>
            ) : null}
            <Field label={t('username')} htmlFor="user_username">
              <input id="user_username" name="username" required maxLength={120} />
            </Field>
            <Field label={choose('显示名称', 'Weergavenaam')} htmlFor="display_name">
              <input id="display_name" name="display_name" required maxLength={160} />
            </Field>
            <Field label={choose('临时密码', 'Tijdelijk wachtwoord')} htmlFor="user_password" hint={choose('至少 12 个字符。', 'Minimaal 12 tekens.')}>
              <input
                id="user_password"
                name="password"
                type="password"
                minLength={12}
                required
                autoComplete="new-password"
              />
            </Field>
            <Field label={choose('角色', 'Rol')} htmlFor="role_codes" hint={choose('角色由后端定义。', 'Rollen worden door de backend bepaald。')}>
              <select id="role_codes" name="role_codes" defaultValue="staff" required>
                {roleOptions.map((role) => (
                  <option key={role.code} value={role.code}>
                    {role.label} — {role.detail}
                  </option>
                ))}
              </select>
            </Field>
            <SubmitButton pending={pending || stores.length === 0}>
              {stores.length === 0 ? choose('需要门店访问权限', 'Vestigingstoegang vereist') : choose('创建员工', 'Medewerker aanmaken')}
            </SubmitButton>
          </form>
        </details>
      ) : null}
      {canWrite && stores.length === 0 ? (
        <div className="notice notice-warning">
          {choose('创建员工需要可读取的已分配门店。请联系所有者同时授予 organization:read 和 identity:write。', 'Voor het aanmaken van medewerkers is een leesbare toegewezen vestiging nodig. Vraag een eigenaar om organization:read én identity:write toe te kennen.')}
        </div>
      ) : null}
      {resource.loading ? <LoadingState label={choose('正在加载员工…', 'Medewerkers laden…')} /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.users.length === 0 ? (
        <EmptyState title={choose('暂无员工账号', 'Geen medewerkersaccounts')} detail={choose('尚未创建员工账号。', 'Er zijn nog geen medewerkersaccounts aangemaakt。')} />
      ) : null}
      {resource.data?.users.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{choose('员工', 'Medewerker')}</th><th>{t('status')}</th><th>{choose('最近登录', 'Laatste login')}</th><th>{t('version')}</th><th>{t('action')}</th>
              </tr>
            </thead>
            <tbody>
              {resource.data.users.map((user) => (
                <tr key={user.id}>
                  <td>
                    <strong>{user.display_name}</strong>
                    <br />
                    <span className="muted">
                      {user.username} · {shortId(user.id)}
                    </span>
                  </td>
                  <td>
                    <StatusBadge value={user.active} />
                  </td>
                  <td>{formatDateTime(user.last_login_at)}</td>
                  <td>{user.version}</td>
                  <td>
                    {canWrite ? (
                      <button
                        type="button"
                        className="button button-secondary"
                        disabled={user.id === currentUserId && user.active}
                        onClick={() => toggleStatus(user)}
                        title={
                          user.id === currentUserId && user.active
                            ? choose('后端不允许用户停用自己的账号。', 'De backend staat niet toe dat gebruikers hun eigen account deactiveren.')
                            : undefined
                        }
                      >
                        {user.id === currentUserId && user.active
                          ? choose('当前用户', 'Huidige gebruiker')
                          : user.active
                            ? choose('停用', 'Deactiveren')
                            : choose('启用', 'Activeren')}
                      </button>
                    ) : (
                      '—'
                    )}
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
