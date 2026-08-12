import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { KioskApi } from './api';
import { App } from './App';
import type { KioskOrder, KioskReceipt, Quote, StoreCatalog } from './types';

const catalog: StoreCatalog = {
  store_id: 'store-1',
  locale: 'nl-NL',
  currency: 'EUR',
  price_book_id: 'book-1',
  categories: [
    {
      id: 'hot',
      code: 'HOT',
      name: 'Warme dranken',
      products: [
        {
          id: 'latte',
          sku: 'LATTE',
          name: 'Latte',
          description: 'Espresso met zachte melk.',
          image_url: null,
          price_minor: 350,
          currency: 'EUR',
          tax_category_code: 'DRINK',
          allergen_data: { contains: ['melk'] },
          option_groups: [
            {
              id: 'size',
              code: 'SIZE',
              name: 'Formaat',
              minimum_selections: 1,
              maximum_selections: 1,
              values: [
                { id: 'small', code: 'SMALL', name: 'Klein', price_delta_minor: 0 },
                { id: 'large', code: 'LARGE', name: 'Groot', price_delta_minor: 75 },
              ],
            },
          ],
        },
        {
          id: 'espresso',
          sku: 'ESPRESSO',
          name: 'Espresso',
          description: 'Krachtig en kort.',
          image_url: null,
          price_minor: 250,
          currency: 'EUR',
          tax_category_code: 'DRINK',
          allergen_data: {},
          option_groups: [],
        },
      ],
    },
  ],
};

beforeEach(() => {
  sessionStorage.clear();
});

const quote: Quote = {
  id: 'quote-1',
  status: 'ACTIVE',
  store_id: 'store-1',
  kiosk_id: 'kiosk-1',
  currency: 'EUR',
  locale: 'nl-NL',
  prices_include_tax: true,
  subtotal_minor: 425,
  discount_minor: 0,
  net_minor: 390,
  tax_minor: 35,
  total_minor: 425,
  expires_at: '2026-08-12T11:00:00Z',
  items: [
    {
      line_number: 1,
      product_id: 'latte',
      sku: 'LATTE',
      name: 'Latte',
      quantity: 1,
      unit_price_minor: 350,
      option_total_minor: 75,
      discount_minor: 0,
      net_minor: 390,
      tax_minor: 35,
      line_total_minor: 425,
      options: [
        {
          option_value_id: 'large',
          group_name: 'Formaat',
          name: 'Groot',
          price_delta_minor: 75,
        },
      ],
      allergen_snapshot: { contains: ['melk'] },
    },
  ],
  tax_lines: [
    { tax_category_code: 'DRINK', tax_rate_ppm: 90_000, taxable_minor: 390, tax_minor: 35 },
  ],
};

function order(paymentStatus: KioskOrder['payment_status']): KioskOrder {
  return {
    id: 'order-1',
    display_number: '042',
    status: paymentStatus === 'PAID' ? 'CONFIRMED' : 'DRAFT',
    payment_status: paymentStatus,
    currency: 'EUR',
    locale: 'nl-NL',
    prices_include_tax: true,
    subtotal_minor: 425,
    discount_minor: 0,
    net_minor: 390,
    tax_minor: 35,
    total_minor: 425,
    paid_minor: paymentStatus === 'PAID' ? 425 : 0,
    refunded_minor: 0,
    items: [
      {
        line_number: 1,
        name: 'Latte',
        quantity: 1,
        unit_price_minor: 350,
        option_total_minor: 75,
        discount_minor: 0,
        net_minor: 390,
        tax_minor: 35,
        line_total_minor: 425,
        allergen_snapshot: { contains: ['melk'] },
        options: [{ group_name: 'Formaat', name: 'Groot', price_delta_minor: 75 }],
      },
    ],
    payment_attempts: [
      {
        id: 'attempt-1',
        payment_method: 'CONTACTLESS',
        status: paymentStatus,
        amount_minor: 425,
        currency: 'EUR',
      },
    ],
  };
}

const receipt: KioskReceipt = {
  receipt_type: 'SALE',
  receipt_number: 'AMS-20260812-000042',
  locale: 'nl-NL',
  currency: 'EUR',
  generated_at: '2026-08-12T10:05:00Z',
  document: {
    legal_entity: { name: 'Smart Drink BV', vat_number: 'NL123456789B01' },
    order: { order_number: 'AMS-20260812-000042' },
    amounts: { total_minor: 425 },
    items: [{ line_number: 1, name: 'Latte', quantity: 1, line_total_minor: 425 }],
  },
};

function apiMock(overrides: Partial<KioskApi> = {}): KioskApi {
  return {
    getStoreStatus: vi.fn().mockResolvedValue({
      store_id: 'store-1',
      accepting_orders: true,
      currency: 'EUR',
      locale: 'nl-NL',
    }),
    heartbeat: vi.fn().mockResolvedValue({
      resource_id: 'kiosk-1',
      server_time: '2026-08-12T10:00:00Z',
    }),
    getCatalog: vi.fn().mockResolvedValue(catalog),
    createQuote: vi.fn().mockResolvedValue(quote),
    createOrder: vi.fn().mockResolvedValue(order('INITIATED')),
    getOrder: vi.fn().mockResolvedValue(order('PAID')),
    retryPayment: vi.fn().mockResolvedValue(order('INITIATED')),
    executePayment: vi.fn().mockResolvedValue(order('PAID')),
    reconcilePayment: vi.fn().mockResolvedValue(order('PAID')),
    getReceipts: vi.fn().mockResolvedValue([receipt]),
    ...overrides,
  };
}

async function addLargeLatte() {
  await screen.findByRole('heading', { name: 'Warme dranken' });
  fireEvent.click(screen.getByRole('button', { name: 'Latte toevoegen' }));
  const dialog = screen.getByRole('dialog', { name: 'Latte' });
  fireEvent.click(within(dialog).getByRole('radio', { name: /Groot/ }));
  fireEvent.click(within(dialog).getByRole('button', { name: /Toevoegen/ }));
}

async function reachPayment(api: KioskApi) {
  render(<App api={api} />);
  await addLargeLatte();
  fireEvent.click(screen.getByRole('button', { name: 'Bestelling controleren' }));
  await screen.findByRole('heading', { name: 'Klopt je bestelling?' });
  fireEvent.click(screen.getByRole('button', { name: /Betalen/ }));
}

describe('Customer kiosk ordering workflow', () => {
  it('sends device heartbeats and blocks new orders while the store is paused', async () => {
    const api = apiMock({
      getStoreStatus: vi.fn().mockResolvedValue({
        store_id: 'store-1',
        accepting_orders: false,
        currency: 'EUR',
        locale: 'nl-NL',
      }),
    });
    render(<App api={api} />);

    expect(await screen.findByText('Nieuwe bestellingen zijn gepauzeerd')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Latte toevoegen' })).toBeDisabled();
    expect(vi.mocked(api.heartbeat)).toHaveBeenCalledTimes(1);
    expect(vi.mocked(api.getStoreStatus)).toHaveBeenCalledTimes(1);
  });

  it('validates required product options before adding a line', async () => {
    render(<App api={apiMock()} />);
    await screen.findByRole('heading', { name: 'Warme dranken' });
    fireEvent.click(screen.getByRole('button', { name: 'Latte toevoegen' }));
    const dialog = screen.getByRole('dialog', { name: 'Latte' });
    fireEvent.click(within(dialog).getByRole('button', { name: /Toevoegen/ }));
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Kies één optie voor Formaat.');
    expect(dialog).toBeInTheDocument();
  });

  it('keeps focus inside the product dialog and closes it with Escape', async () => {
    render(<App api={apiMock()} />);
    await screen.findByRole('heading', { name: 'Warme dranken' });
    const opener = screen.getByRole('button', { name: 'Latte toevoegen' });
    fireEvent.click(opener);
    const dialog = screen.getByRole('dialog', { name: 'Latte' });
    const closeButton = within(dialog).getByRole('button', { name: 'Sluiten' });
    const addButton = within(dialog).getByRole('button', { name: /Toevoegen/ });

    expect(closeButton).toHaveFocus();
    addButton.focus();
    fireEvent.keyDown(window, { key: 'Tab' });
    expect(closeButton).toHaveFocus();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Latte' })).not.toBeInTheDocument();
    await waitFor(() => expect(opener).toHaveFocus());
  });

  it('quotes the configured cart and renders authoritative tax totals', async () => {
    const api = apiMock();
    render(<App api={api} />);
    await addLargeLatte();

    expect(screen.getAllByText('€ 4,25').length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole('button', { name: 'Bestelling controleren' }));

    await screen.findByRole('heading', { name: 'Klopt je bestelling?' });
    expect(vi.mocked(api.createQuote)).toHaveBeenCalledWith('nl-NL', [
      { product_id: 'latte', quantity: 1, option_value_ids: ['large'] },
    ]);
    expect(screen.getByText('Prijzen zijn inclusief BTW.')).toBeInTheDocument();
    expect(screen.getByText('€ 0,35')).toBeInTheDocument();
  });

  it('does not persist catalog image URLs in the checkout recovery snapshot', async () => {
    const baseCategory = catalog.categories[0]!;
    const catalogWithImage: StoreCatalog = {
      ...catalog,
      categories: [
        {
          ...baseCategory,
          products: baseCategory.products.map((product) => ({
            ...product,
            image_url: `https://cdn.example/${product.id}.jpg`,
          })),
        },
      ],
    };
    render(<App api={apiMock({ getCatalog: vi.fn().mockResolvedValue(catalogWithImage) })} />);
    await addLargeLatte();

    await waitFor(() =>
      expect(sessionStorage.getItem('smart-drink:kiosk-checkout-session')).toContain('Latte'),
    );
    const stored = JSON.parse(
      sessionStorage.getItem('smart-drink:kiosk-checkout-session') ?? '{}',
    ) as { cart?: Array<{ product?: { image_url?: unknown } }> };
    expect(stored.cart?.[0]?.product?.image_url).toBeNull();
    expect(sessionStorage.getItem('smart-drink:kiosk-checkout-session')).not.toContain(
      'cdn.example',
    );
  });

  it('enforces the backend limit of 100 total cart items', async () => {
    const latte = catalog.categories[0]!.products[0]!;
    sessionStorage.setItem(
      'smart-drink:kiosk-checkout-session',
      JSON.stringify({
        version: 1,
        savedAt: Date.now(),
        step: 'browse',
        cart: [
          {
            key: 'latte:large',
            product: latte,
            optionValueIds: ['large'],
            selectedOptions: [
              {
                groupName: 'Formaat',
                value: latte.option_groups[0]!.values[1]!,
              },
            ],
            quantity: 100,
          },
        ],
        quote: null,
        order: null,
        paymentMethod: 'CONTACTLESS',
        orderIdempotencyKey: null,
        retryIdempotencyKey: null,
      }),
    );
    render(<App api={apiMock()} />);
    await screen.findByRole('heading', { name: 'Warme dranken' });

    fireEvent.click(screen.getByRole('button', { name: 'Espresso toevoegen' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Maximaal 100 producten');
    expect(screen.getByLabelText('100 producten')).toBeInTheDocument();
    expect(screen.queryByText('101 producten')).not.toBeInTheDocument();
  });

  it('completes payment and displays the backend receipt and pickup number', async () => {
    const api = apiMock();
    await reachPayment(api);

    await screen.findByRole('heading', { name: 'Bedankt!' });
    expect(screen.getByText('042')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Betaalbewijs' })).toBeInTheDocument();
    expect(screen.getByText('AMS-20260812-000042')).toBeInTheDocument();
    expect(vi.mocked(api.createOrder)).toHaveBeenCalledWith(
      'quote-1',
      'CONTACTLESS',
      expect.stringMatching(/^kiosk-order-/),
    );
    expect(vi.mocked(api.executePayment)).toHaveBeenCalledWith('attempt-1');
    expect(vi.mocked(api.getReceipts)).toHaveBeenCalledWith('order-1');
  });

  it('reconciles an unknown payment and never creates a second attempt', async () => {
    const api = apiMock({
      executePayment: vi.fn().mockResolvedValue(order('UNKNOWN')),
      reconcilePayment: vi.fn().mockResolvedValue(order('PAID')),
    });
    await reachPayment(api);

    expect(await screen.findByRole('heading', { name: 'Controle nodig' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Opnieuw betalen' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Controleer betaling' }));
    await screen.findByRole('heading', { name: 'Bedankt!' });
    expect(vi.mocked(api.reconcilePayment)).toHaveBeenCalledWith('attempt-1');
    expect(vi.mocked(api.retryPayment)).not.toHaveBeenCalled();
  });

  it('creates and executes a retry attempt only after a declined payment', async () => {
    const retried = {
      ...order('INITIATED'),
      payment_attempts: [
        ...order('FAILED').payment_attempts,
        {
          id: 'attempt-2',
          payment_method: 'CONTACTLESS' as const,
          status: 'INITIATED' as const,
          amount_minor: 425,
          currency: 'EUR',
        },
      ],
    };
    const executePayment = vi
      .fn()
      .mockResolvedValueOnce(order('FAILED'))
      .mockResolvedValueOnce(order('PAID'));
    const api = apiMock({
      executePayment,
      retryPayment: vi.fn().mockResolvedValue(retried),
    });
    await reachPayment(api);

    expect(await screen.findByRole('heading', { name: 'Niet gelukt' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Opnieuw betalen' }));
    await screen.findByRole('heading', { name: 'Bedankt!' });
    expect(vi.mocked(api.retryPayment)).toHaveBeenCalledWith(
      'order-1',
      'CONTACTLESS',
      expect.stringMatching(/^kiosk-retry-/),
    );
    expect(executePayment).toHaveBeenLastCalledWith('attempt-2');
  });

  it('recovers a paid order when the execute response is lost', async () => {
    const api = apiMock({
      executePayment: vi.fn().mockRejectedValue(new TypeError('connection dropped')),
      getOrder: vi.fn().mockResolvedValue(order('PAID')),
    });
    await reachPayment(api);

    await screen.findByRole('heading', { name: 'Bedankt!' });
    expect(vi.mocked(api.getOrder)).toHaveBeenCalledWith('order-1');
    expect(vi.mocked(api.getReceipts)).toHaveBeenCalledWith('order-1');
    expect(screen.getByText('042')).toBeInTheDocument();
  });

  it('can safely resume the same attempt when payment execution never reached the API', async () => {
    const executePayment = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('connection dropped'))
      .mockResolvedValueOnce(order('PAID'));
    const api = apiMock({
      executePayment,
      getOrder: vi.fn().mockResolvedValue(order('INITIATED')),
    });
    await reachPayment(api);

    expect(await screen.findByRole('heading', { name: 'Betaling gestart' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Betaling hervatten' }));
    await screen.findByRole('heading', { name: 'Bedankt!' });
    expect(executePayment).toHaveBeenNthCalledWith(1, 'attempt-1');
    expect(executePayment).toHaveBeenNthCalledWith(2, 'attempt-1');
    expect(vi.mocked(api.retryPayment)).not.toHaveBeenCalled();
  });

  it('restores an unfinished order without creating another order or payment attempt', async () => {
    sessionStorage.setItem(
      'smart-drink:kiosk-checkout-session',
      JSON.stringify({
        version: 1,
        savedAt: Date.now(),
        step: 'payment',
        cart: [],
        quote: null,
        order: order('UNKNOWN'),
        paymentMethod: 'CONTACTLESS',
        orderIdempotencyKey: 'stable-order-key',
        retryIdempotencyKey: null,
      }),
    );
    const api = apiMock({ getOrder: vi.fn().mockResolvedValue(order('UNKNOWN')) });
    render(<App api={api} />);

    expect(await screen.findByRole('heading', { name: 'Controle nodig' })).toBeInTheDocument();
    expect(vi.mocked(api.getOrder)).toHaveBeenCalledWith('order-1');
    expect(vi.mocked(api.createOrder)).not.toHaveBeenCalled();
    expect(vi.mocked(api.retryPayment)).not.toHaveBeenCalled();
    expect(vi.mocked(api.executePayment)).not.toHaveBeenCalled();
  });

  it('retries receipt retrieval without repeating payment', async () => {
    const getReceipts = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('receipt service disconnected'))
      .mockResolvedValueOnce([receipt]);
    const api = apiMock({ getReceipts });
    await reachPayment(api);

    await screen.findByRole('heading', { name: 'Bedankt!' });
    fireEvent.click(screen.getByRole('button', { name: 'Betaalbewijs opnieuw ophalen' }));
    expect(await screen.findByRole('heading', { name: 'Betaalbewijs' })).toBeInTheDocument();
    expect(getReceipts).toHaveBeenCalledTimes(2);
    expect(vi.mocked(api.executePayment)).toHaveBeenCalledTimes(1);
  });

  it('shows a recoverable catalog error without exposing technical details', async () => {
    const getCatalog = vi
      .fn()
      .mockRejectedValueOnce(new TypeError('socket internals'))
      .mockResolvedValueOnce(catalog);
    render(<App api={apiMock({ getCatalog })} />);

    expect(
      await screen.findByRole('heading', { name: 'Menu niet beschikbaar' }),
    ).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Onverwachte fout');
    expect(screen.queryByText('socket internals')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Opnieuw proberen' }));
    await waitFor(() =>
      expect(screen.getByRole('heading', { name: 'Warme dranken' })).toBeInTheDocument(),
    );
  });
});
