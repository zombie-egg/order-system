import { useState, type FormEvent } from 'react';
import { errorMessage, normalizeApiBaseUrl } from '../api';
import { Field, SubmitButton } from '../components';

export interface LoginValues {
  apiBaseUrl: string;
  tenantCode: string;
  username: string;
  password: string;
}

export function LoginPage({
  defaultApiUrl,
  onLogin,
}: {
  defaultApiUrl: string;
  onLogin: (values: LoginValues) => Promise<void>;
}) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const value = (name: string) => {
      const entry = data.get(name);
      return typeof entry === 'string' ? entry : '';
    };
    setPending(true);
    setError(null);
    void onLogin({
      apiBaseUrl: normalizeApiBaseUrl(value('apiBaseUrl')),
      tenantCode: value('tenantCode').trim(),
      username: value('username').trim(),
      password: value('password'),
    }).catch((reason: unknown) => {
      setError(reason);
      setPending(false);
    });
  };

  return (
    <main className="login-layout">
      <section className="login-panel" aria-labelledby="login-title">
        <header>
          <p className="eyebrow">SipPilot · 饮航 operations</p>
          <h1 id="login-title">Staff sign in</h1>
          <p>Use an assigned tenant account. Access is restricted by backend permissions.</p>
        </header>
        {error ? (
          <div className="notice notice-error" role="alert">
            {errorMessage(error)}
          </div>
        ) : null}
        <form onSubmit={submit} className="form-stack">
          <Field
            label="API URL"
            htmlFor="apiBaseUrl"
            hint="Override this for staging or a remote edge server."
          >
            <input
              id="apiBaseUrl"
              name="apiBaseUrl"
              type="text"
              defaultValue={defaultApiUrl}
              required
            />
          </Field>
          <Field label="Tenant code" htmlFor="tenantCode">
            <input id="tenantCode" name="tenantCode" autoComplete="organization" required />
          </Field>
          <Field label="Username" htmlFor="username">
            <input id="username" name="username" autoComplete="username" required />
          </Field>
          <Field label="Password" htmlFor="password">
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </Field>
          <SubmitButton pending={pending}>Sign in</SubmitButton>
        </form>
      </section>
    </main>
  );
}
