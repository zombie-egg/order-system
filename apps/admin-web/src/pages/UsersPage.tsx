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

const ROLE_OPTIONS: ReadonlyArray<{
  code: (typeof STAFF_ROLE_CODES)[number];
  label: string;
  detail: string;
}> = [
  {
    code: 'manager',
    label: 'Manager',
    detail: 'Store setup, ordering, payments, review, reporting and audit.',
  },
  {
    code: 'staff',
    label: 'Staff',
    detail: 'Orders, payments, kitchen work and read-only manual review.',
  },
  {
    code: 'reviewer',
    label: 'Reviewer',
    detail: 'Orders, payments, manual-review resolution and audit.',
  },
  {
    code: 'owner',
    label: 'Owner',
    detail: 'Every tenant and store permission, including staff administration.',
  },
] as const;

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
          setSuccess(`User ${user.username} created.`);
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
        setSuccess(`User ${updated.username} ${updated.active ? 'activated' : 'deactivated'}.`);
      }, setMutationError);
  };

  return (
    <section>
      <PageHeader
        title="Staff accounts"
        description="Tenant users are scoped to stores and backend roles."
      />
      <MutationMessage error={mutationError} success={success} />
      {canWrite ? (
        <details className="card form-disclosure">
          <summary>Create staff account</summary>
          <form className="form-grid" onSubmit={createUser}>
            <Field label="Store" htmlFor="store_id">
              <select id="store_id" name="store_id" required defaultValue="">
                <option value="" disabled>
                  Select a store
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
                Store names require organization:read. Ask an owner to grant it before creating
                store-scoped staff.
              </p>
            ) : null}
            <Field label="Username" htmlFor="user_username">
              <input id="user_username" name="username" required maxLength={120} />
            </Field>
            <Field label="Display name" htmlFor="display_name">
              <input id="display_name" name="display_name" required maxLength={160} />
            </Field>
            <Field label="Temporary password" htmlFor="user_password" hint="Minimum 12 characters.">
              <input
                id="user_password"
                name="password"
                type="password"
                minLength={12}
                required
                autoComplete="new-password"
              />
            </Field>
            <Field label="Role" htmlFor="role_codes" hint="Roles are defined by the Backend.">
              <select id="role_codes" name="role_codes" defaultValue="staff" required>
                {ROLE_OPTIONS.map((role) => (
                  <option key={role.code} value={role.code}>
                    {role.label} — {role.detail}
                  </option>
                ))}
              </select>
            </Field>
            <SubmitButton pending={pending || stores.length === 0}>
              {stores.length === 0 ? 'Store access required' : 'Create user'}
            </SubmitButton>
          </form>
        </details>
      ) : null}
      {canWrite && stores.length === 0 ? (
        <div className="notice notice-warning">
          Staff creation needs a readable assigned store. Ask an owner to grant organization:read
          together with identity:write.
        </div>
      ) : null}
      {resource.loading ? <LoadingState label="Loading users…" /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.users.length === 0 ? (
        <EmptyState title="No users" detail="No staff accounts have been created." />
      ) : null}
      {resource.data?.users.length ? (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>User</th>
                <th>Status</th>
                <th>Last login</th>
                <th>Version</th>
                <th>Action</th>
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
                            ? 'The Backend does not allow users to deactivate their own account.'
                            : undefined
                        }
                      >
                        {user.id === currentUserId && user.active
                          ? 'Current user'
                          : user.active
                            ? 'Deactivate'
                            : 'Activate'}
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
