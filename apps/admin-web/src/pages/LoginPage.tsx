import { useState, type FormEvent } from 'react';
import { errorMessage, normalizeApiBaseUrl } from '../api';
import { Field, SubmitButton } from '../components';
import { LanguageSwitch, useAdminI18n } from '../i18n';

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
  const { t, choose } = useAdminI18n();
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
          <div className="login-heading-row"><p className="eyebrow">SipPilot · 饮航 · {t('admin')}</p><LanguageSwitch /></div>
          <h1 id="login-title">{t('signIn')}</h1>
          <p>{choose('请使用已分配的租户账号登录。访问权限由后端角色控制。', 'Log in met een toegewezen tenantaccount. Toegang wordt bepaald door backendrollen.')}</p>
        </header>
        {error ? (
          <div className="notice notice-error" role="alert">
            {errorMessage(error)}
          </div>
        ) : null}
        <form onSubmit={submit} className="form-stack">
          <Field
            label={t('api')}
            htmlFor="apiBaseUrl"
            hint={choose('可在此修改测试环境或远程边缘服务器地址。', 'Pas hier het adres van de testomgeving of externe edge-server aan.')}
          >
            <input
              id="apiBaseUrl"
              name="apiBaseUrl"
              type="text"
              defaultValue={defaultApiUrl}
              required
            />
          </Field>
          <Field label={t('tenantCode')} htmlFor="tenantCode">
            <input id="tenantCode" name="tenantCode" autoComplete="organization" required />
          </Field>
          <Field label={t('username')} htmlFor="username">
            <input id="username" name="username" autoComplete="username" required />
          </Field>
          <Field label={t('password')} htmlFor="password">
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
            />
          </Field>
          <SubmitButton pending={pending}>{t('signIn')}</SubmitButton>
        </form>
      </section>
    </main>
  );
}
