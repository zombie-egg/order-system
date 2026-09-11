import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  heartbeat,
  listTickets,
  normalizeApiBaseUrl,
  transitionTicket,
  type FulfillmentFailureReason,
  type FulfillmentStatus,
  type FulfillmentTicket,
  type KitchenApiCredentials,
} from './api';
import {
  clearKitchenSession,
  readKitchenSession,
  writeKitchenSession,
  type StoredKitchenSession,
} from './session';

const DEFAULT_API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000/api/v1';
// Backend policy can mark an endpoint stale after as little as five seconds.
// Four seconds keeps the display inside that commercial safety envelope until
// the heartbeat contract exposes a server-recommended interval.
const HEARTBEAT_INTERVAL_MS = 4_000;
const QUEUE_POLL_INTERVAL_MS = 8_000;
const DISPLAY_CLOCK_INTERVAL_MS = 30_000;
const AGE_WARNING_MS = 5 * 60_000;
const AGE_CRITICAL_MS = 10 * 60_000;

const STATUS_LABELS: Record<FulfillmentStatus, string> = {
  NOT_RELEASED: 'Niet vrijgegeven', QUEUED: 'Nieuwe bestelling', ACKNOWLEDGED: 'Geaccepteerd', PREPARING: 'In bereiding',
  READY: 'Klaar om af te halen', COLLECTED: 'Afgehaald', ON_HOLD: 'Gepauzeerd', UNFULFILLABLE: 'Niet te bereiden', CANCELLED: 'Geannuleerd',
};

const FAILURE_REASONS: ReadonlyArray<{ value: FulfillmentFailureReason; label: string }> = [
  { value: 'OUT_OF_STOCK', label: 'Ingrediënt of product niet op voorraad' },
  { value: 'STAFF_CAPACITY', label: 'Onvoldoende personeel' },
  {
    value: 'MANUAL_WORKSTATION_EQUIPMENT_FAILURE',
    label: 'Storing bij werkstation of apparatuur',
  },
  { value: 'ORDER_ERROR', label: 'Fout in de bestelling' },
  { value: 'ALLERGEN_OR_RECIPE_ISSUE', label: 'Probleem met allergenen of recept' },
  { value: 'STORE_CLOSING', label: 'Vestiging sluit binnenkort' },
  { value: 'OTHER', label: 'Andere operationele reden' },
];

const ALLOWED_TRANSITIONS: Partial<Record<FulfillmentStatus, FulfillmentStatus[]>> = {
  QUEUED: ['ACKNOWLEDGED', 'ON_HOLD', 'UNFULFILLABLE'],
  ACKNOWLEDGED: ['PREPARING', 'ON_HOLD', 'UNFULFILLABLE'],
  PREPARING: ['READY', 'ON_HOLD', 'UNFULFILLABLE'],
  ON_HOLD: ['ACKNOWLEDGED', 'PREPARING', 'UNFULFILLABLE'],
  READY: ['COLLECTED'],
};

const PRIMARY_TRANSITION: Partial<Record<FulfillmentStatus, FulfillmentStatus>> = {
  QUEUED: 'ACKNOWLEDGED',
  ACKNOWLEDGED: 'PREPARING',
  PREPARING: 'READY',
  ON_HOLD: 'PREPARING',
  READY: 'COLLECTED',
};

const ACTION_LABELS: Partial<Record<FulfillmentStatus, string>> = {
  ACKNOWLEDGED: 'Bestelling accepteren', PREPARING: 'Bereiding starten', READY: 'Markeren als klaar', COLLECTED: 'Markeren als afgehaald', ON_HOLD: 'Bestelling pauzeren',
};

type TicketAgeLevel = 'fresh' | 'warning' | 'critical';

interface TicketAgePresentation {
  accessibleLabel: string;
  level: TicketAgeLevel;
  shortLabel: string;
  title: string;
}

interface ConnectionFormState {
  apiBaseUrl: string;
  endpointId: string;
  endpointKey: string;
}

interface FailureDialogState {
  ticket: FulfillmentTicket;
  reason: FulfillmentFailureReason | '';
  detail: string;
  validationError: string | null;
}

function initialConnectionForm(session: StoredKitchenSession | null): ConnectionFormState {
  return {
    apiBaseUrl: session?.apiBaseUrl ?? DEFAULT_API_BASE_URL,
    endpointId: session?.endpointId ?? '',
    endpointKey: session?.endpointKey ?? '',
  };
}

function formatError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : 'Er is een onbekende fout opgetreden.';
  }

  const suffix = error.correlationId ? ` Referentienummer: ${error.correlationId}.` : '';
  switch (error.status) {
    case 401:
      return `De werkstationgegevens zijn ongeldig of verlopen. Controleer de werkstation-ID en werkstationsleutel.${suffix}`;
    case 403:
      return `Dit werkstation heeft geen toegang tot de bereidingswachtrij.${suffix}`;
    case 409:
      return `Deze bestelling is op een ander scherm bijgewerkt. De wachtrij is vernieuwd.${suffix}`;
    case 422:
      return `De statuswijziging is geweigerd vanwege ongeldige gegevens.${suffix}`;
    default:
      return `${error.message}${suffix}`;
  }
}

function formatSnapshotValue(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  if (value === null || value === undefined) {
    return '';
  }
  if (Array.isArray(value)) {
    return value.map(formatSnapshotValue).filter(Boolean).join(', ');
  }
  return JSON.stringify(value);
}

function snapshotValues(snapshot: Record<string, unknown>): string[] {
  return Object.entries(snapshot)
    .filter(([, value]) => value !== null && value !== '' && value !== false)
    .map(([key, value]) => {
      const label = key.replaceAll('_', ' ');
      if (Array.isArray(value)) {
        return `${label}: ${formatSnapshotValue(value)}`;
      }
      if (typeof value === 'object') {
        return `${label}: ${JSON.stringify(value)}`;
      }
      return `${label}: ${formatSnapshotValue(value)}`;
    });
}

function isTerminal(status: FulfillmentStatus): boolean {
  return ['COLLECTED', 'UNFULFILLABLE', 'CANCELLED'].includes(status);
}

function validTimestamp(value: string | null): number | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function ticketStageTimestamp(ticket: FulfillmentTicket): number | null {
  switch (ticket.status) {
    case 'ACKNOWLEDGED':
      return validTimestamp(ticket.acknowledged_at);
    case 'PREPARING':
    case 'ON_HOLD':
      return validTimestamp(ticket.started_at) ?? validTimestamp(ticket.acknowledged_at);
    case 'READY':
      return validTimestamp(ticket.ready_at);
    default:
      return null;
  }
}

function ticketAgePresentation(
  ticket: FulfillmentTicket,
  observedAt: number,
  now: number,
): TicketAgePresentation {
  const stageTimestamp = ticketStageTimestamp(ticket);
  const start = stageTimestamp ?? observedAt;
  const elapsed = Math.max(0, now - start);
  const roundedMinutes = Math.floor(elapsed / 60_000);
  const shortLabel = roundedMinutes < 1 ? 'Zojuist' : `${roundedMinutes} min`;
  const level: TicketAgeLevel =
    elapsed >= AGE_CRITICAL_MS ? 'critical' : elapsed >= AGE_WARNING_MS ? 'warning' : 'fresh';

  if (stageTimestamp === null) {
    return {
      accessibleLabel:
        roundedMinutes < 1
          ? 'Zojuist op dit scherm verschenen'
          : `${roundedMinutes} minuten op dit scherm`,
      level,
      shortLabel,
      title: 'Gemeten vanaf het moment dat dit scherm de bestelling ontving.',
    };
  }

  const stageLabel: Partial<Record<FulfillmentStatus, string>> = {
    ACKNOWLEDGED: 'Geaccepteerd',
    PREPARING: 'In bereiding',
    ON_HOLD: 'In deze fase',
    READY: 'Klaar om af te halen',
  };
  const label = stageLabel[ticket.status] ?? 'Huidige fase';
  return {
    accessibleLabel:
      roundedMinutes < 1
        ? `${label}, minder dan één minuut`
        : `${label}, ${roundedMinutes} minuten`,
    level,
    shortLabel,
    title: 'Gemeten vanaf de door de server geregistreerde start van deze fase.',
  };
}

function transitionLabel(ticket: FulfillmentTicket, status: FulfillmentStatus): string {
  if (ticket.status === 'ON_HOLD' && status === 'PREPARING') {
    return 'Bereiding hervatten';
  }
  if (ticket.status === 'ON_HOLD' && status === 'ACKNOWLEDGED') {
    return 'Terug naar geaccepteerd';
  }
  return ACTION_LABELS[status] ?? STATUS_LABELS[status];
}

function ConnectionScreen({
  previousSession,
  onConnected,
  initialMessage,
}: {
  previousSession: StoredKitchenSession | null;
  onConnected: (session: StoredKitchenSession) => void;
  initialMessage: string | null;
}) {
  const [form, setForm] = useState(() => initialConnectionForm(previousSession));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(initialMessage);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const apiBaseUrl = normalizeApiBaseUrl(form.apiBaseUrl);
      const endpointId = form.endpointId.trim();
      const endpointKey = form.endpointKey.trim();
      if (!endpointId || !endpointKey) {
        throw new Error('Vul de werkstation-ID en werkstationsleutel in.');
      }

      const credentials: KitchenApiCredentials = {
        apiBaseUrl,
        endpointId,
        endpointKey,
      };

      await heartbeat(credentials);
      await listTickets(credentials);

      writeKitchenSession(credentials);
      onConnected(credentials);
    } catch (caught) {
      setError(formatError(caught));
    } finally {
      setSubmitting(false);
    }
  }

  function updateField(field: keyof ConnectionFormState, value: string) {
    setForm((current) => ({ ...current, [field]: value }));
  }

  return (
    <main className="connection-shell">
      <section className="connection-panel" aria-labelledby="connection-title">
        <aside className="connection-overview">
          <div className="connection-brand">
            <span className="brand-mark brand-mark-large" aria-hidden="true">
              SD
            </span>
            <span>SipPilot</span>
          </div>
          <div>
            <p className="eyebrow">Vestigingsservice · Handmatige bereiding</p>
          <h1 id="connection-title">Bereidingsscherm verbinden</h1>
            <p className="supporting-text">
              Verbind dit scherm met een ingericht werkstation via de werkstation-ID en werkstationsleutel.
            </p>
          </div>
          <div className="provisioning-note">
            <strong>Voor opening</strong>
            <span>Controleer of de Edge API actief is en dit werkstation is ingeschakeld.</span>
          </div>
        </aside>

        <div className="connection-workspace">
          {error ? (
            <div className="alert alert-error" role="alert">
              {error}
            </div>
          ) : null}

          <form className="connection-form" onSubmit={(event) => void submit(event)}>
            <label>
              Edge API-adres
              <input
                type="url"
                required
                autoCapitalize="none"
                spellCheck={false}
                value={form.apiBaseUrl}
                onChange={(event) => updateField('apiBaseUrl', event.target.value)}
              />
            </label>

            <div className="form-grid">
              <label>
              Werkstation-ID
                <input
                  required
                  autoComplete="off"
                  autoCapitalize="none"
                  spellCheck={false}
                  value={form.endpointId}
                  onChange={(event) => updateField('endpointId', event.target.value)}
                />
              </label>
              <label>
              Werkstationsleutel
                <input
                  type="password"
                  required
                  autoComplete="off"
                  value={form.endpointKey}
                  onChange={(event) => updateField('endpointKey', event.target.value)}
                />
              </label>
            </div>


            <button
              className="button button-primary connect-button"
              type="submit"
              disabled={submitting}
            >
              {submitting ? 'Controleren…' : 'Scherm verbinden'}
            </button>
          </form>

          <p className="security-note">
            De werkstationsleutel wordt alleen in dit browsertabblad bewaard. Gebruik op beheerde productieapparaten een veilige sleutelvoorziening.
          </p>
        </div>
      </section>
    </main>
  );
}

function TicketCard({
  ticket,
  busy,
  offline,
  error,
  observedAt,
  now,
  onTransition,
}: {
  ticket: FulfillmentTicket;
  busy: boolean;
  offline: boolean;
  error: string | null;
  observedAt: number;
  now: number;
  onTransition: (ticket: FulfillmentTicket, status: FulfillmentStatus) => void;
}) {
  const transitions = ALLOWED_TRANSITIONS[ticket.status] ?? [];
  const primaryTransition = PRIMARY_TRANSITION[ticket.status];
  const secondaryTransitions = transitions.filter(
    (status) => status !== primaryTransition && status !== 'UNFULFILLABLE',
  );
  const age = ticketAgePresentation(ticket, observedAt, now);
  const priority = ticket.priority > 0;

  return (
    <article
      className={`ticket ticket-${ticket.status.toLowerCase()} age-${age.level}${
        priority ? ' ticket-priority' : ''
      }${offline ? ' ticket-offline' : ''}`}
      aria-busy={busy}
      aria-labelledby={`ticket-${ticket.id}`}
    >
      {busy ? (
        <span className="sr-only" role="status">
          Bestelling {ticket.display_number} wordt bijgewerkt
        </span>
      ) : null}
      <header className="ticket-header">
        <div>
          <div className="ticket-flags">
            {priority ? <span className="priority-badge">Prioriteit {ticket.priority}</span> : null}
            {ticket.generation_number > 1 ? (
              <span className="remake-badge">Herbereiding {ticket.generation_number}</span>
            ) : null}
          </div>
          <p className="ticket-number" id={`ticket-${ticket.id}`}>
            #{ticket.display_number}
          </p>
          <span className="fulfillment-badge">
            {ticket.fulfillment_type === 'TAKEAWAY' ? 'Meenemen' : 'Hier eten'}
          </span>
        </div>
        <div className="ticket-timing">
          <span className={`age-badge age-badge-${age.level}`} title={age.title}>
            <span aria-hidden="true">{age.shortLabel}</span>
            <span className="sr-only">{age.accessibleLabel}</span>
          </span>
          <span className={`status-badge status-${ticket.status.toLowerCase()}`}>
            {STATUS_LABELS[ticket.status]}
          </span>
        </div>
      </header>

      <ul className="ticket-items" aria-label={`Producten van bestelling ${ticket.display_number}`}>
        {ticket.items.map((item) => {
          const preparation = snapshotValues(item.preparation_snapshot);
          const allergens = snapshotValues(item.allergen_snapshot);
          return (
            <li key={item.order_item_id}>
              <div className="item-title">
                <span className="quantity">{item.quantity}×</span>
                <strong>{item.name}</strong>
              </div>
              {item.options && item.options.length > 0 ? (
                <p className="item-options">{item.options.join(' · ')}</p>
              ) : null}
              {preparation.length > 0 ? (
                <ul className="item-notes" aria-label="Bereidingsinstructies">
                  {preparation.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
              {allergens.length > 0 ? (
                <p className="allergen-note">Allergenen: {allergens.join('; ')}</p>
              ) : null}
            </li>
          );
        })}
      </ul>

      {error ? (
        <div className="ticket-error" role="alert">
          {error}
        </div>
      ) : null}

      <footer className="ticket-actions">
        {primaryTransition ? (
          <button
            className={`button button-primary action-${primaryTransition.toLowerCase()}`}
            type="button"
            disabled={busy || offline}
            onClick={() => onTransition(ticket, primaryTransition)}
          >
            {busy ? 'Bijwerken…' : transitionLabel(ticket, primaryTransition)}
          </button>
        ) : null}
        {secondaryTransitions.map((status) => (
          <button
            className="button button-secondary"
            type="button"
            disabled={busy || offline}
            key={status}
            onClick={() => onTransition(ticket, status)}
          >
            {transitionLabel(ticket, status)}
          </button>
        ))}
        {transitions.includes('UNFULFILLABLE') ? (
          <button
            className="button button-danger"
            type="button"
            disabled={busy || offline}
            onClick={() => onTransition(ticket, 'UNFULFILLABLE')}
          >
            Niet te bereiden
          </button>
        ) : null}
      </footer>
    </article>
  );
}

function FailureDialog({
  state,
  busy,
  offline,
  onChange,
  onCancel,
  onSubmit,
}: {
  state: FailureDialogState;
  busy: boolean;
  offline: boolean;
  onChange: (state: FailureDialogState) => void;
  onCancel: () => void;
  onSubmit: () => void;
}) {
  const reasonRef = useRef<HTMLSelectElement>(null);
  const busyRef = useRef(busy);

  useEffect(() => {
    busyRef.current = busy;
  }, [busy]);

  useEffect(() => {
    const previouslyFocused =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    reasonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape' && !busyRef.current) {
        event.preventDefault();
        onCancel();
        return;
      }
      if (event.key !== 'Tab') return;

      const dialog = reasonRef.current?.closest<HTMLElement>('[role="dialog"]');
      if (!dialog) return;
      const focusable = Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not([disabled]), select:not([disabled]), textarea:not([disabled]), input:not([disabled])',
        ),
      );
      if (focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [onCancel]);

  return (
    <div className="dialog-backdrop">
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="failure-title">
        <div className="dialog-heading">
          <p className="dialog-kicker">Handmatige controle vereist</p>
          <h2 id="failure-title">Bestelling #{state.ticket.display_number} kan niet worden bereid</h2>
          <p>
            Hiermee wordt de bestelling direct uit de bereidingswachtrij verwijderd en voor handmatige controle vastgelegd.
          </p>
        </div>
        {state.validationError ? (
          <div className="alert alert-error" role="alert">
            {state.validationError}
          </div>
        ) : null}
        {offline ? (
          <div className="alert alert-warning" role="alert">
            Het scherm is offline. Herstel de verbinding voordat u deze actie bevestigt.
          </div>
        ) : null}
        <label htmlFor="failure-reason">
          Operationele reden
          <select
            id="failure-reason"
            ref={reasonRef}
            required
            value={state.reason}
            onChange={(event) =>
              onChange({
                ...state,
                reason: event.target.value as FulfillmentFailureReason | '',
                validationError: null,
              })
            }
          >
            <option value="">Kies een reden</option>
            {FAILURE_REASONS.map((reason) => (
              <option value={reason.value} key={reason.value}>
                {reason.label}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor="failure-detail">
          Toelichting
          <textarea
            id="failure-detail"
            required
            maxLength={1000}
            rows={4}
            placeholder="Beschrijf wat is gecontroleerd en waarom deze betaalde bestelling niet kan worden bereid. Vermeld geen betaalkaartgegevens."
            value={state.detail}
            onChange={(event) =>
              onChange({ ...state, detail: event.target.value, validationError: null })
            }
          />
          <span className="field-help">Verplicht · {state.detail.length}/1000 tekens</span>
        </label>
        <div className="dialog-actions">
          <button
            className="button button-secondary"
            type="button"
            disabled={busy}
            onClick={onCancel}
          >
            Annuleren
          </button>
          <button
            className="button button-danger"
            type="button"
            disabled={busy || offline}
            onClick={onSubmit}
          >
            {busy ? 'Verzenden…' : 'Bevestigen als niet te bereiden'}
          </button>
        </div>
      </section>
    </div>
  );
}

function QueueScreen({
  session,
  onDisconnect,
}: {
  session: StoredKitchenSession;
  onDisconnect: (message?: string) => void;
}) {
  const [tickets, setTickets] = useState<FulfillmentTicket[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [online, setOnline] = useState(navigator.onLine);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [lastHeartbeatAt, setLastHeartbeatAt] = useState<Date | null>(null);
  const [displayNow, setDisplayNow] = useState(() => Date.now());
  const [busyTicketId, setBusyTicketId] = useState<string | null>(null);
  const [ticketErrors, setTicketErrors] = useState<Record<string, string>>({});
  const [failureDialog, setFailureDialog] = useState<FailureDialogState | null>(null);
  const queueRequestActive = useRef(false);
  const heartbeatRequestActive = useRef(false);
  const observedTicketAt = useRef<Record<string, number>>({});

  const handleAuthFailure = useCallback(
    (error: ApiError) => {
      if (error.status === 401) {
        onDisconnect(formatError(error));
        return true;
      }
      return false;
    },
    [onDisconnect],
  );

  const refreshQueue = useCallback(
    async (manual = false) => {
      if (queueRequestActive.current) {
        return;
      }
      if (!navigator.onLine) {
        setLoading(false);
        return;
      }
      queueRequestActive.current = true;
      if (manual) setRefreshing(true);
      try {
        const nextTickets = await listTickets(session);
        const receivedAt = Date.now();
        const nextObservedTicketAt: Record<string, number> = {};
        for (const ticket of nextTickets) {
          nextObservedTicketAt[ticket.id] = observedTicketAt.current[ticket.id] ?? receivedAt;
        }
        observedTicketAt.current = nextObservedTicketAt;
        setTickets(nextTickets);
        setLastUpdatedAt(new Date(receivedAt));
        setDisplayNow(receivedAt);
        setGlobalError(null);
      } catch (error) {
        if (!(error instanceof ApiError) || !handleAuthFailure(error)) {
          setGlobalError(formatError(error));
        }
      } finally {
        queueRequestActive.current = false;
        setLoading(false);
        setRefreshing(false);
      }
    },
    [handleAuthFailure, session],
  );

  const sendHeartbeat = useCallback(async () => {
    if (heartbeatRequestActive.current || !navigator.onLine) {
      return;
    }
    heartbeatRequestActive.current = true;
    try {
      const response = await heartbeat(session);
      setLastHeartbeatAt(new Date(response.heartbeat_at));
    } catch (error) {
      if (!(error instanceof ApiError) || !handleAuthFailure(error)) {
        setGlobalError(formatError(error));
      }
    } finally {
      heartbeatRequestActive.current = false;
    }
  }, [handleAuthFailure, session]);

  useEffect(() => {
    const updateOnlineState = () => {
      setOnline(navigator.onLine);
      if (navigator.onLine) {
        void sendHeartbeat();
        void refreshQueue();
      }
    };
    window.addEventListener('online', updateOnlineState);
    window.addEventListener('offline', updateOnlineState);
    return () => {
      window.removeEventListener('online', updateOnlineState);
      window.removeEventListener('offline', updateOnlineState);
    };
  }, [refreshQueue, sendHeartbeat]);

  useEffect(() => {
    void sendHeartbeat();
    void refreshQueue();
    const heartbeatTimer = window.setInterval(() => void sendHeartbeat(), HEARTBEAT_INTERVAL_MS);
    const queueTimer = window.setInterval(() => void refreshQueue(), QUEUE_POLL_INTERVAL_MS);
    const displayClockTimer = window.setInterval(
      () => setDisplayNow(Date.now()),
      DISPLAY_CLOCK_INTERVAL_MS,
    );
    return () => {
      window.clearInterval(heartbeatTimer);
      window.clearInterval(queueTimer);
      window.clearInterval(displayClockTimer);
    };
  }, [refreshQueue, sendHeartbeat]);

  async function applyTransition(
    ticket: FulfillmentTicket,
    status: FulfillmentStatus,
    reason?: FulfillmentFailureReason,
    detail?: string,
  ) {
    setBusyTicketId(ticket.id);
    setTicketErrors((current) => ({ ...current, [ticket.id]: '' }));
    try {
      const updated = await transitionTicket(session, ticket.id, {
        to_status: status,
        expected_version: ticket.version,
        ...(reason ? { failure_reason_code: reason } : {}),
        ...(detail ? { failure_detail: detail } : {}),
      });
      setTickets((current) =>
        isTerminal(updated.status)
          ? current.filter((candidate) => {
              if (candidate.id === updated.id) {
                delete observedTicketAt.current[candidate.id];
                return false;
              }
              return true;
            })
          : current.map((candidate) => (candidate.id === updated.id ? updated : candidate)),
      );
      const changedAt = Date.now();
      setLastUpdatedAt(new Date(changedAt));
      setDisplayNow(changedAt);
      setFailureDialog(null);
    } catch (error) {
      if (error instanceof ApiError && handleAuthFailure(error)) {
        return;
      }
      setTicketErrors((current) => ({ ...current, [ticket.id]: formatError(error) }));
      if (error instanceof ApiError && error.status === 409) {
        await refreshQueue();
      }
    } finally {
      setBusyTicketId(null);
    }
  }

  function requestTransition(ticket: FulfillmentTicket, status: FulfillmentStatus) {
    if (!online) {
      return;
    }
    if (status === 'UNFULFILLABLE') {
      setFailureDialog({ ticket, reason: '', detail: '', validationError: null });
      return;
    }
    void applyTransition(ticket, status);
  }

  function submitFailure() {
    if (!failureDialog || !online) return;
    const detail = failureDialog.detail.trim();
    if (!failureDialog.reason || !detail) {
      setFailureDialog({
        ...failureDialog,
        validationError: 'Kies een operationele reden en vul een toelichting in.',
      });
      return;
    }
    void applyTransition(failureDialog.ticket, 'UNFULFILLABLE', failureDialog.reason, detail);
  }

  const closeFailureDialog = useCallback(() => setFailureDialog(null), []);

  const groupedTickets = useMemo(() => {
    const groups: Array<{
      title: string;
      statuses: FulfillmentStatus[];
      tickets: FulfillmentTicket[];
    }> = [
      { title: 'Nieuwe bestellingen', statuses: ['QUEUED', 'ACKNOWLEDGED'], tickets: [] },
      { title: 'In bereiding', statuses: ['PREPARING', 'ON_HOLD'], tickets: [] },
      { title: 'Klaar om af te halen', statuses: ['READY'], tickets: [] },
    ];
    for (const ticket of tickets) {
      groups.find((group) => group.statuses.includes(ticket.status))?.tickets.push(ticket);
    }
    for (const group of groups) {
      group.tickets.sort((left, right) => {
        if (left.priority !== right.priority) return right.priority - left.priority;
        const leftObservedAt = observedTicketAt.current[left.id] ?? displayNow;
        const rightObservedAt = observedTicketAt.current[right.id] ?? displayNow;
        return leftObservedAt - rightObservedAt;
      });
    }
    return groups;
  }, [displayNow, tickets]);

  const priorityTicketCount = useMemo(
    () => tickets.filter((ticket) => ticket.priority > 0).length,
    [tickets],
  );
  return (
    <main className="queue-shell">
      <header className="app-header">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">
            SD
          </span>
          <div>
            <p className="eyebrow">Werkstation voor handmatige bereiding</p>
            <h1>Bereidingsscherm</h1>
          </div>
        </div>
        <div className="header-actions">
          <div className={`connection-status ${online ? 'is-online' : 'is-offline'}`}>
            <span className={`status-dot ${online ? 'online' : 'offline'}`} aria-hidden="true" />
            <span>
              <strong aria-live="polite">{online ? 'Verbonden' : 'Offline'}</strong>
              {lastHeartbeatAt ? (
                <small>Heartbeat {lastHeartbeatAt.toLocaleTimeString('nl-NL')}</small>
              ) : null}
            </span>
          </div>
          <button
            className="button button-secondary"
            type="button"
            disabled={refreshing || !online}
            onClick={() => void refreshQueue(true)}
          >
            {refreshing ? 'Vernieuwen…' : 'Wachtrij vernieuwen'}
          </button>
          <button className="button button-quiet" type="button" onClick={() => onDisconnect()}>
            Verbinding verbreken
          </button>
        </div>
      </header>

      {!online ? (
        <div className="alert alert-warning" role="alert">
          Het scherm is offline. Herstel de API-verbinding voordat u bestellingen verwerkt.
        </div>
      ) : null}
      {globalError ? (
        <div className="alert alert-error global-alert" role="alert">
          <span>{globalError}</span>
          <button
            className="button button-secondary"
            type="button"
            disabled={!online || refreshing}
            onClick={() => void refreshQueue(true)}
          >
            Opnieuw proberen
          </button>
        </div>
      ) : null}

      <div className="queue-summary">
        <div className="summary-metrics" aria-live="polite" aria-atomic="true">
          <span className="summary-metric">
            <strong>{tickets.length}</strong>
            <span>Actief</span>
          </span>
          <span
            className={`summary-metric summary-priority${priorityTicketCount ? ' has-priority' : ''}`}
          >
            <strong>{priorityTicketCount}</strong>
            <span>Prioriteit</span>
          </span>
        </div>
        <span className="last-updated">
          {lastUpdatedAt
            ? `Bijgewerkt om ${lastUpdatedAt.toLocaleTimeString('nl-NL')}`
            : 'Wachten op eerste update'}
        </span>
      </div>

      {loading ? (
        <section className="empty-state" aria-busy="true">
          <h2>Bereidingswachtrij laden…</h2>
          <p>Betaalde bestellingen voor dit werkstation worden opgehaald.</p>
        </section>
      ) : tickets.length === 0 && !online ? (
        <section className="empty-state empty-state-offline">
          <h2>Wachtrij niet beschikbaar terwijl u offline bent</h2>
          <p>
            Verbind dit scherm opnieuw met de Edge API. Na herstel worden bestellingen automatisch geladen.
          </p>
        </section>
      ) : tickets.length === 0 ? (
        <section className="empty-state">
          <h2>Geen bestellingen om te bereiden</h2>
          <p>Het scherm wordt automatisch vernieuwd zodra een betaalde bestelling binnenkomt.</p>
        </section>
      ) : (
        <div className="queue-grid">
          {groupedTickets.map((group) => {
            const columnStatus = group.statuses[0]!;
            return (
              <section
                className={`queue-column queue-column-${columnStatus.toLowerCase()}`}
                aria-labelledby={`column-${columnStatus}`}
                id={`queue-stage-${columnStatus.toLowerCase()}`}
                key={group.title}
              >
                <header className="column-header">
                  <h2 id={`column-${columnStatus}`}>{group.title}</h2>
                  <span aria-label={`${group.tickets.length} bestellingen`}>{group.tickets.length}</span>
                </header>
                {group.tickets.length > 0 ? (
                  <div className="ticket-stack">
                    {group.tickets.map((ticket) => (
                      <TicketCard
                        ticket={ticket}
                        busy={busyTicketId === ticket.id}
                        offline={!online}
                        error={ticketErrors[ticket.id] || null}
                        observedAt={observedTicketAt.current[ticket.id] ?? displayNow}
                        now={displayNow}
                        onTransition={requestTransition}
                        key={ticket.id}
                      />
                    ))}
                  </div>
                ) : (
                  <p className="column-empty">Geen bestellingen in deze fase</p>
                )}
              </section>
            );
          })}
        </div>
      )}

      {failureDialog ? (
        <FailureDialog
          state={failureDialog}
          busy={busyTicketId === failureDialog.ticket.id}
          offline={!online}
          onChange={setFailureDialog}
          onCancel={closeFailureDialog}
          onSubmit={submitFailure}
        />
      ) : null}
    </main>
  );
}

export function App() {
  const [session, setSession] = useState<StoredKitchenSession | null>(() => readKitchenSession());
  const [connectionMessage, setConnectionMessage] = useState<string | null>(null);

  const disconnect = useCallback((message?: string) => {
    clearKitchenSession();
    setSession(null);
    setConnectionMessage(message ?? null);
  }, []);

  if (!session) {
    return (
      <ConnectionScreen
        previousSession={null}
        onConnected={(connectedSession) => {
          setConnectionMessage(null);
          setSession(connectedSession);
        }}
        initialMessage={connectionMessage}
      />
    );
  }

  return <QueueScreen session={session} onDisconnect={disconnect} />;
}
