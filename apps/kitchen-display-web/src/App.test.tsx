import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { App } from './App';
import type { FulfillmentTicket } from './api';
import { writeKitchenSession, type StoredKitchenSession } from './session';

const session: StoredKitchenSession = {
  apiBaseUrl: 'http://127.0.0.1:8000/api/v1',
  endpointId: '11111111-1111-1111-1111-111111111111',
  endpointKey: 'endpoint-secret',
};

const ticket: FulfillmentTicket = {
  id: '22222222-2222-2222-2222-222222222222',
  order_id: '33333333-3333-3333-3333-333333333333',
  station_id: '44444444-4444-4444-4444-444444444444',
  source_ticket_id: null,
  generation_number: 1,
  display_number: 'A-101',
  status: 'QUEUED',
  priority: 10,
  failure_reason_code: null,
  failure_detail: null,
  acknowledged_at: null,
  started_at: null,
  ready_at: null,
  collected_at: null,
  version: 3,
  items: [
    {
      order_item_id: '55555555-5555-5555-5555-555555555555',
      quantity: 2,
      name: 'Iced matcha latte',
      preparation_snapshot: { sweetness: 'less sweet', temperature: 'cold' },
      allergen_snapshot: { contains: ['milk'] },
    },
  ],
};

function response(data: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({
      'content-type': 'application/json',
      'x-correlation-id': 'server-reference',
    }),
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response;
}

function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.href;
  return input.url;
}

function heartbeatResponse() {
  return response({
    endpoint_id: session.endpointId,
    station_id: ticket.station_id,
    heartbeat_at: '2026-08-12T12:00:00Z',
    version: 2,
  });
}

beforeEach(() => {
  sessionStorage.clear();
  vi.restoreAllMocks();
  Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: true });
});

function queueFetch(tickets: FulfillmentTicket[]) {
  return vi.fn<typeof fetch>((input) => {
    const url = requestUrl(input);
    if (url.endsWith('/fulfillment/heartbeat')) return Promise.resolve(heartbeatResponse());
    if (url.endsWith('/fulfillment/tickets')) return Promise.resolve(response(tickets));
    throw new Error(`Unexpected request: ${url}`);
  });
}

describe('Kitchen Display', () => {
  it('connects with device credentials before loading the paid-order queue', async () => {
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = requestUrl(input);
      if (url.endsWith('/fulfillment/heartbeat')) {
        const headers = new Headers(init?.headers);
        expect(headers.get('X-Endpoint-ID')).toBe(session.endpointId);
        expect(headers.get('X-Endpoint-Key')).toBe(session.endpointKey);
        return Promise.resolve(heartbeatResponse());
      }
      if (url.endsWith('/fulfillment/tickets')) {
        const headers = new Headers(init?.headers);
        expect(headers.get('Authorization')).toBeNull();
        expect(headers.get('X-Endpoint-ID')).toBe(session.endpointId);
        expect(headers.get('X-Endpoint-Key')).toBe(session.endpointKey);
        return Promise.resolve(response([ticket]));
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    expect(screen.getByRole('heading', { name: 'Bereidingsscherm verbinden' })).toBeInTheDocument();
    expect(screen.getByText(/alleen in dit browsertabblad bewaard/i)).toBeInTheDocument();
    expect(screen.queryByLabelText('Tenantcode')).not.toBeInTheDocument();
    expect(screen.queryByLabelText('Gebruikersnaam')).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Werkstation-ID'), {
      target: { value: session.endpointId },
    });
    fireEvent.change(screen.getByLabelText('Werkstationsleutel'), {
      target: { value: session.endpointKey },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Scherm verbinden' }));

    expect(await screen.findByRole('heading', { name: 'Bereidingsscherm' })).toBeInTheDocument();
    expect(await screen.findByText('#A-101')).toBeInTheDocument();
    expect(screen.getByText('2×')).toBeInTheDocument();
    expect(screen.getByText('Iced matcha latte')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalled();
  });

  it('requires a reason and detail before marking a paid order unfulfillable', async () => {
    writeKitchenSession(session);
    let transitionBody: unknown;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = requestUrl(input);
      if (url.endsWith('/fulfillment/heartbeat')) return Promise.resolve(heartbeatResponse());
      if (url.endsWith('/fulfillment/tickets')) return Promise.resolve(response([ticket]));
      if (url.endsWith(`/fulfillment/tickets/${ticket.id}/transition`)) {
        if (typeof init?.body !== 'string') {
          throw new Error('Expected a JSON request body.');
        }
        transitionBody = JSON.parse(init.body) as unknown;
        return Promise.resolve(
          response({
            ...ticket,
            status: 'UNFULFILLABLE',
            failure_reason_code: 'OUT_OF_STOCK',
            failure_detail: 'Matcha ingredient unavailable after stock check.',
            version: 4,
          }),
        );
      }
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);
    expect(await screen.findByText('#A-101')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Niet te bereiden' }));
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen als niet te bereiden' }));
    expect(
      screen.getByText('Kies een operationele reden en vul een toelichting in.'),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Operationele reden'), {
      target: { value: 'OUT_OF_STOCK' },
    });
    fireEvent.change(screen.getByRole('textbox', { name: /Toelichting/ }), {
      target: { value: 'Matcha ingredient unavailable after stock check.' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Bevestigen als niet te bereiden' }));

    await waitFor(() => {
      expect(transitionBody).toEqual({
        to_status: 'UNFULFILLABLE',
        expected_version: 3,
        failure_reason_code: 'OUT_OF_STOCK',
        failure_detail: 'Matcha ingredient unavailable after stock check.',
      });
    });
    expect(await screen.findByRole('heading', { name: 'Geen bestellingen om te bereiden' })).toBeInTheDocument();
  });

  it('clears an invalid session and returns the operator to sign-in on HTTP 401', async () => {
    writeKitchenSession(session);
    const fetchMock = vi.fn<typeof fetch>((input) => {
      const url = requestUrl(input);
      if (url.endsWith('/fulfillment/heartbeat')) return Promise.resolve(heartbeatResponse());
      return Promise.resolve(
        response(
          {
            title: 'unauthorized',
            status: 401,
            detail: 'Access token is invalid or expired',
            correlation_id: 'auth-reference',
            details: {},
          },
          401,
        ),
      );
    });
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(
      await screen.findByRole('heading', { name: 'Bereidingsscherm verbinden' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/ongeldig of verlopen/i);
    expect(sessionStorage.length).toBe(0);
  });

  it('surfaces priority and overdue work ahead of lower-priority tickets', async () => {
    writeKitchenSession(session);
    const now = Date.now();
    const regularTicket: FulfillmentTicket = {
      ...ticket,
      id: '66666666-6666-6666-6666-666666666666',
      display_number: 'A-100',
      status: 'PREPARING',
      priority: 0,
      started_at: new Date(now - 2 * 60_000).toISOString(),
    };
    const overduePriorityTicket: FulfillmentTicket = {
      ...ticket,
      id: '77777777-7777-7777-7777-777777777777',
      display_number: 'A-102',
      status: 'PREPARING',
      priority: 20,
      started_at: new Date(now - 12 * 60_000).toISOString(),
    };
    vi.stubGlobal('fetch', queueFetch([regularTicket, overduePriorityTicket]));

    const { container } = render(<App />);

    expect(await screen.findByText('#A-102')).toBeInTheDocument();
    expect(screen.getByText('Prioriteit 20')).toBeInTheDocument();
    expect(screen.getByText('12 min')).toBeInTheDocument();
    const cards = Array.from(container.querySelectorAll('.ticket'));
    expect(cards[0]).toHaveTextContent('#A-102');
    expect(cards[0]).toHaveClass('ticket-priority', 'age-critical');
  });

  it('moves focus into the destructive dialog and closes it with Escape', async () => {
    writeKitchenSession(session);
    vi.stubGlobal('fetch', queueFetch([ticket]));

    render(<App />);
    const cannotFulfil = await screen.findByRole('button', { name: 'Niet te bereiden' });
    cannotFulfil.focus();
    fireEvent.click(cannotFulfil);

    const reason = screen.getByLabelText('Operationele reden');
    expect(reason).toHaveFocus();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(cannotFulfil).toHaveFocus();
  });

  it('keeps visible tickets read-only while the Windows device is offline', async () => {
    writeKitchenSession(session);
    vi.stubGlobal('fetch', queueFetch([ticket]));

    render(<App />);
    expect(await screen.findByText('#A-101')).toBeInTheDocument();

    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
    fireEvent(window, new Event('offline'));

    expect(screen.getByRole('alert')).toHaveTextContent(/Herstel de API-verbinding/i);
    expect(screen.getByRole('button', { name: 'Bestelling accepteren' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Wachtrij vernieuwen' })).toBeDisabled();
  });

  it('shows a recoverable offline state instead of an endless first-load spinner', async () => {
    writeKitchenSession(session);
    Object.defineProperty(window.navigator, 'onLine', { configurable: true, value: false });
    const fetchMock = vi.fn<typeof fetch>();
    vi.stubGlobal('fetch', fetchMock);

    render(<App />);

    expect(
      await screen.findByRole('heading', { name: 'Wachtrij niet beschikbaar terwijl u offline bent' }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Bereidingswachtrij laden/i)).not.toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
