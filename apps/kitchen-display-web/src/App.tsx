import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  createAccessToken,
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
  NOT_RELEASED: 'Not released',
  QUEUED: 'New',
  ACKNOWLEDGED: 'Accepted',
  PREPARING: 'Preparing',
  READY: 'Ready',
  COLLECTED: 'Collected',
  ON_HOLD: 'On hold',
  UNFULFILLABLE: 'Cannot fulfil',
  CANCELLED: 'Cancelled',
};

const FAILURE_REASONS: ReadonlyArray<{ value: FulfillmentFailureReason; label: string }> = [
  { value: 'OUT_OF_STOCK', label: 'Ingredient or item out of stock' },
  { value: 'STAFF_CAPACITY', label: 'Insufficient staff capacity' },
  {
    value: 'MANUAL_WORKSTATION_EQUIPMENT_FAILURE',
    label: 'Manual workstation or equipment failure',
  },
  { value: 'ORDER_ERROR', label: 'Order information is incorrect' },
  { value: 'ALLERGEN_OR_RECIPE_ISSUE', label: 'Allergen or recipe issue' },
  { value: 'STORE_CLOSING', label: 'Store is closing' },
  { value: 'OTHER', label: 'Other operational reason' },
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
  ACKNOWLEDGED: 'Accept order',
  PREPARING: 'Start preparing',
  READY: 'Mark ready',
  COLLECTED: 'Mark collected',
  ON_HOLD: 'Put on hold',
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
  tenantCode: string;
  username: string;
  password: string;
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
    tenantCode: session?.tenantCode ?? '',
    username: session?.username ?? '',
    password: '',
  };
}

function formatError(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return error instanceof Error ? error.message : 'An unexpected error occurred.';
  }

  const suffix = error.correlationId ? ` Reference: ${error.correlationId}.` : '';
  switch (error.status) {
    case 401:
      return `The staff session or endpoint credentials are invalid or expired.${suffix}`;
    case 403:
      return `This staff account is not allowed to operate the kitchen queue.${suffix}`;
    case 409:
      return `This ticket changed on another display. The queue has been refreshed.${suffix}`;
    case 422:
      return `The transition was rejected because its data is invalid.${suffix}`;
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
  const shortLabel = roundedMinutes < 1 ? 'Just arrived' : `${roundedMinutes} min`;
  const level: TicketAgeLevel =
    elapsed >= AGE_CRITICAL_MS ? 'critical' : elapsed >= AGE_WARNING_MS ? 'warning' : 'fresh';

  if (stageTimestamp === null) {
    return {
      accessibleLabel:
        roundedMinutes < 1
          ? 'Just arrived on this display'
          : `On this display for ${roundedMinutes} minutes`,
      level,
      shortLabel,
      title: 'Measured from when this display first received the ticket.',
    };
  }

  const stageLabel: Partial<Record<FulfillmentStatus, string>> = {
    ACKNOWLEDGED: 'Accepted',
    PREPARING: 'Preparing',
    ON_HOLD: 'In current workflow',
    READY: 'Ready',
  };
  const label = stageLabel[ticket.status] ?? 'In current stage';
  return {
    accessibleLabel:
      roundedMinutes < 1
        ? `${label} less than a minute ago`
        : `${label} for ${roundedMinutes} minutes`,
    level,
    shortLabel,
    title: 'Measured from the server-recorded time for the current preparation stage.',
  };
}

function transitionLabel(ticket: FulfillmentTicket, status: FulfillmentStatus): string {
  if (ticket.status === 'ON_HOLD' && status === 'PREPARING') {
    return 'Resume preparing';
  }
  if (ticket.status === 'ON_HOLD' && status === 'ACKNOWLEDGED') {
    return 'Return to accepted';
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
        throw new Error('Endpoint ID and endpoint key are required.');
      }

      const token = await createAccessToken(apiBaseUrl, {
        tenant_code: form.tenantCode.trim(),
        username: form.username.trim(),
        password: form.password,
      });
      const credentials: KitchenApiCredentials = {
        apiBaseUrl,
        endpointId,
        endpointKey,
        accessToken: token.access_token,
      };

      await heartbeat(credentials);
      await listTickets(credentials);

      const session: StoredKitchenSession = {
        ...credentials,
        accessTokenExpiresAt: token.expires_at,
        tenantCode: form.tenantCode.trim(),
        username: form.username.trim(),
      };
      writeKitchenSession(session);
      onConnected(session);
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
            <span>SipPilot · 饮航</span>
          </div>
          <div>
            <p className="eyebrow">Store edge · Manual preparation</p>
            <h1 id="connection-title">Connect kitchen display</h1>
            <p className="supporting-text">
              Sign in a kitchen operator and pair this Windows display with its provisioned
              endpoint.
            </p>
          </div>
          <div className="provisioning-note">
            <strong>Before the shift</strong>
            <span>Confirm the Edge API is running and this station has an active endpoint.</span>
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
              Edge API address
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
                Endpoint ID
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
                Endpoint key
                <input
                  type="password"
                  required
                  autoComplete="off"
                  value={form.endpointKey}
                  onChange={(event) => updateField('endpointKey', event.target.value)}
                />
              </label>
            </div>

            <div className="form-grid">
              <label>
                Tenant code
                <input
                  required
                  autoCapitalize="none"
                  autoComplete="organization"
                  value={form.tenantCode}
                  onChange={(event) => updateField('tenantCode', event.target.value)}
                />
              </label>
              <label>
                Username
                <input
                  required
                  autoCapitalize="none"
                  autoComplete="username"
                  value={form.username}
                  onChange={(event) => updateField('username', event.target.value)}
                />
              </label>
            </div>

            <label>
              Password
              <input
                type="password"
                required
                autoComplete="current-password"
                value={form.password}
                onChange={(event) => updateField('password', event.target.value)}
              />
            </label>

            <button
              className="button button-primary connect-button"
              type="submit"
              disabled={submitting}
            >
              {submitting ? 'Checking credentials…' : 'Connect display'}
            </button>
          </form>

          <p className="security-note">
            Phase 4 stores the endpoint key and short-lived staff token only in this browser tab
            session. Production Windows provisioning must inject secrets through the managed device
            boundary; never compile a device key into the web bundle.
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
          Updating order {ticket.display_number}
        </span>
      ) : null}
      <header className="ticket-header">
        <div>
          <div className="ticket-flags">
            {priority ? <span className="priority-badge">Priority {ticket.priority}</span> : null}
            {ticket.generation_number > 1 ? (
              <span className="remake-badge">Remake {ticket.generation_number}</span>
            ) : null}
          </div>
          <p className="ticket-number" id={`ticket-${ticket.id}`}>
            #{ticket.display_number}
          </p>
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

      <ul className="ticket-items" aria-label={`Items for order ${ticket.display_number}`}>
        {ticket.items.map((item) => {
          const preparation = snapshotValues(item.preparation_snapshot);
          const allergens = snapshotValues(item.allergen_snapshot);
          return (
            <li key={item.order_item_id}>
              <div className="item-title">
                <span className="quantity">{item.quantity}×</span>
                <strong>{item.name}</strong>
              </div>
              {preparation.length > 0 ? (
                <ul className="item-notes" aria-label="Preparation instructions">
                  {preparation.map((note) => (
                    <li key={note}>{note}</li>
                  ))}
                </ul>
              ) : null}
              {allergens.length > 0 ? (
                <p className="allergen-note">Allergen information: {allergens.join('; ')}</p>
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
            {busy ? 'Updating…' : transitionLabel(ticket, primaryTransition)}
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
            Cannot fulfil
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
          <p className="dialog-kicker">Manual review required</p>
          <h2 id="failure-title">Order #{state.ticket.display_number} cannot be fulfilled</h2>
          <p>
            This immediately removes the ticket from the kitchen queue and opens a case for manual
            review.
          </p>
        </div>
        {state.validationError ? (
          <div className="alert alert-error" role="alert">
            {state.validationError}
          </div>
        ) : null}
        {offline ? (
          <div className="alert alert-warning" role="alert">
            The display is offline. Reconnect before confirming this action.
          </div>
        ) : null}
        <label htmlFor="failure-reason">
          Operational reason
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
            <option value="">Select a reason</option>
            {FAILURE_REASONS.map((reason) => (
              <option value={reason.value} key={reason.value}>
                {reason.label}
              </option>
            ))}
          </select>
        </label>
        <label htmlFor="failure-detail">
          Review detail
          <textarea
            id="failure-detail"
            required
            maxLength={1000}
            rows={4}
            placeholder="Describe what staff checked and why the paid order cannot be made. Do not enter payment-card data."
            value={state.detail}
            onChange={(event) =>
              onChange({ ...state, detail: event.target.value, validationError: null })
            }
          />
          <span className="field-help">Required · {state.detail.length}/1000 characters</span>
        </label>
        <div className="dialog-actions">
          <button
            className="button button-secondary"
            type="button"
            disabled={busy}
            onClick={onCancel}
          >
            Cancel
          </button>
          <button
            className="button button-danger"
            type="button"
            disabled={busy || offline}
            onClick={onSubmit}
          >
            {busy ? 'Submitting…' : 'Confirm cannot fulfil'}
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
        validationError: 'Select an operational reason and enter review detail.',
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
      { title: 'New orders', statuses: ['QUEUED', 'ACKNOWLEDGED'], tickets: [] },
      { title: 'In preparation', statuses: ['PREPARING', 'ON_HOLD'], tickets: [] },
      { title: 'Ready for collection', statuses: ['READY'], tickets: [] },
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
            <p className="eyebrow">Manual preparation station</p>
            <h1>Kitchen Display</h1>
          </div>
        </div>
        <div className="header-actions">
          <div className={`connection-status ${online ? 'is-online' : 'is-offline'}`}>
            <span className={`status-dot ${online ? 'online' : 'offline'}`} aria-hidden="true" />
            <span>
              <strong aria-live="polite">{online ? 'Connected' : 'Offline'}</strong>
              {lastHeartbeatAt ? (
                <small>Heartbeat {lastHeartbeatAt.toLocaleTimeString()}</small>
              ) : null}
            </span>
          </div>
          <button
            className="button button-secondary"
            type="button"
            disabled={refreshing || !online}
            onClick={() => void refreshQueue(true)}
          >
            {refreshing ? 'Refreshing…' : 'Refresh queue'}
          </button>
          <button className="button button-quiet" type="button" onClick={() => onDisconnect()}>
            Disconnect
          </button>
        </div>
      </header>

      {!online ? (
        <div className="alert alert-warning" role="alert">
          This display is offline. Ticket actions are disabled until the Edge API connection
          returns.
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
            Retry
          </button>
        </div>
      ) : null}

      <div className="queue-summary">
        <div className="summary-metrics" aria-live="polite" aria-atomic="true">
          <span className="summary-metric">
            <strong>{tickets.length}</strong>
            <span>Active</span>
          </span>
          <span
            className={`summary-metric summary-priority${priorityTicketCount ? ' has-priority' : ''}`}
          >
            <strong>{priorityTicketCount}</strong>
            <span>Priority</span>
          </span>
        </div>
        <span className="last-updated">
          {lastUpdatedAt
            ? `Updated ${lastUpdatedAt.toLocaleTimeString()}`
            : 'Waiting for first update'}
        </span>
      </div>

      {loading ? (
        <section className="empty-state" aria-busy="true">
          <h2>Loading kitchen queue…</h2>
          <p>Checking the paid-order queue for this preparation station.</p>
        </section>
      ) : tickets.length === 0 && !online ? (
        <section className="empty-state empty-state-offline">
          <h2>Queue unavailable offline</h2>
          <p>
            Reconnect this Windows display to the Edge API. Orders will load automatically when the
            connection returns.
          </p>
        </section>
      ) : tickets.length === 0 ? (
        <section className="empty-state">
          <h2>No active orders</h2>
          <p>The display will refresh automatically when a paid order reaches this station.</p>
        </section>
      ) : (
        <div className="queue-grid">
          {groupedTickets.map((group) => {
            const columnStatus = group.statuses[0]!;
            return (
              <section
                className={`queue-column queue-column-${columnStatus.toLowerCase()}`}
                aria-labelledby={`column-${columnStatus}`}
                key={group.title}
              >
                <header className="column-header">
                  <h2 id={`column-${columnStatus}`}>{group.title}</h2>
                  <span aria-label={`${group.tickets.length} tickets`}>{group.tickets.length}</span>
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
                  <p className="column-empty">No tickets in this stage</p>
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
