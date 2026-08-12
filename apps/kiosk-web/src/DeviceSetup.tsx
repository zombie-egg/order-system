import { type FormEvent, useState } from 'react';
import {
  DEFAULT_API_BASE_URL,
  normalizeKioskApiBaseUrl,
  type KioskRuntimeConfig,
  saveSessionKioskConfig,
} from './api';

interface DeviceSetupProps {
  onConfigured: (config: KioskRuntimeConfig) => void;
}

export function DeviceSetup(props: DeviceSetupProps) {
  const [apiBaseUrl, setApiBaseUrl] = useState(DEFAULT_API_BASE_URL);
  const [kioskId, setKioskId] = useState('');
  const [kioskKey, setKioskKey] = useState('');
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const config = {
        apiBaseUrl: normalizeKioskApiBaseUrl(apiBaseUrl),
        kioskId: kioskId.trim(),
        kioskKey: kioskKey.trim(),
      };
      setError(null);
      saveSessionKioskConfig(config);
      props.onConfigured(config);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'De apparaatgegevens zijn ongeldig.');
    }
  }

  return (
    <main className="setup-page">
      <section className="setup-card" aria-labelledby="setup-title">
        <p className="eyebrow">SipPilot · 饮航 · Device provisioning</p>
        <h1 id="setup-title">Kiosk koppelen</h1>
        <p className="setup-intro">
          Voer de eenmalig uitgegeven apparaatgegevens in. De sleutel blijft alleen in deze
          browsertab en wordt niet in permanente browseropslag bewaard.
        </p>
        <form className="setup-form" onSubmit={submit}>
          {error ? (
            <p className="setup-error" role="alert">
              {error}
            </p>
          ) : null}
          <label>
            Edge API-adres
            <input
              type="url"
              value={apiBaseUrl}
              onChange={(event) => setApiBaseUrl(event.target.value)}
              required
              autoComplete="url"
            />
          </label>
          <label>
            Kiosk-ID
            <input
              value={kioskId}
              onChange={(event) => setKioskId(event.target.value)}
              required
              autoComplete="off"
              spellCheck={false}
            />
          </label>
          <label>
            Kiosk-sleutel
            <input
              type="password"
              value={kioskKey}
              onChange={(event) => setKioskKey(event.target.value)}
              required
              autoComplete="off"
            />
          </label>
          <button className="primary-button" type="submit">
            Verbinden
          </button>
        </form>
        <p className="setup-note">
          Gebruik op een productieapparaat Windows kiosk mode en lever de sleutel via een beveiligd
          provisioningproces.
        </p>
      </section>
    </main>
  );
}
