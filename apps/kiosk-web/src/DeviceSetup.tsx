import { type FormEvent, useState } from 'react';
import {
  DEFAULT_API_BASE_URL,
  type KioskRuntimeConfig,
  saveSessionKioskConfig,
} from './api';

interface DeviceSetupProps {
  onConfigured: (config: KioskRuntimeConfig) => void;
}

export function DeviceSetup(props: DeviceSetupProps) {
  const [kioskId, setKioskId] = useState('');
  const [kioskKey, setKioskKey] = useState('');
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      const config = {
        apiBaseUrl: DEFAULT_API_BASE_URL,
        kioskId: kioskId.trim(),
        kioskKey: kioskKey.trim(),
      };
      setError(null);
      saveSessionKioskConfig(config);
      props.onConfigured(config);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '设备信息无效。');
    }
  }

  return (
    <main className="setup-page">
      <section className="setup-card" aria-labelledby="setup-title">
        <p className="eyebrow">SipPilot · 饮航</p>
        <h1 id="setup-title">连接点单机</h1>
        <p className="setup-intro">
          Voer de eenmalig uitgegeven kioskgegevens van deze vestiging in. De verbinding met de
          SipPilot-service wordt automatisch ingesteld. De sleutel blijft alleen in deze browsertab
          en wordt niet in permanente browseropslag bewaard.
        </p>
        <form className="setup-form" onSubmit={submit}>
          {error ? (
            <p className="setup-error" role="alert">
              {error}
            </p>
          ) : null}
          <label>
            Kiosk-ID van deze vestiging
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
