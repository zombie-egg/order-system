import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from '../api';
import { AdminI18nProvider } from '../i18n';
import type { AdminProductList, StoreWithPolicy } from '../types';
import { ProductsPricingPage } from './ProductsPricingPage';

const store = {
  store: {
    id: 'store-1',
    code: 'AMS-01',
    name: 'Amsterdam Store',
    country_code: 'NL',
    currency: 'EUR',
    locale: 'nl-NL',
    timezone: 'Europe/Amsterdam',
    active: true,
    version: 1,
  },
  policy: {
    store_id: 'store-1',
    accepting_orders: true,
    max_open_tickets: 50,
    kds_heartbeat_seconds: 30,
    printer_fallback_enabled: false,
    takeaway_fee_enabled: false,
    takeaway_fee_minor: 0,
    version: 1,
  },
} satisfies StoreWithPolicy;

const products: AdminProductList = {
  store_id: 'store-1',
  currency: 'EUR',
  price_book_id: 'price-book-1',
  products: [
    {
      id: 'product-1', sku: 'P-1', name: 'Thee', description: '', category_id: null,
      category_name: null, image_url: null, status: 'PUBLISHED', active: true, available: true,
      price_minor: 489, currency: 'EUR', tax_category_code: 'VAT_STANDARD', sort_order: 0,
    version: 1,
    option_rules: [],
    option_prices: {},
    },
    {
      id: 'product-2', sku: 'P-2', name: 'Koffie', description: '', category_id: null,
      category_name: null, image_url: null, status: 'PUBLISHED', active: true, available: true,
      price_minor: 299, currency: 'EUR', tax_category_code: 'VAT_STANDARD', sort_order: 1,
      version: 1,
      option_rules: [],
      option_prices: {},
    },
  ],
};

describe('ProductsPricingPage', () => {
  it('keeps a separate price draft for every product', async () => {
    const request = vi.fn(() => Promise.resolve({}));
    const api = {
      get: vi.fn((path: string) =>
        Promise.resolve(path.endsWith('/products') ? products : []),
      ),
      request,
      post: vi.fn(),
      patch: vi.fn(),
    } as unknown as ApiClient;

    render(
      <AdminI18nProvider>
        <ProductsPricingPage api={api} stores={[store]} canWrite />
      </AdminI18nProvider>,
    );

    const inputs = await screen.findAllByPlaceholderText('价格 €');
    expect(inputs[0]).toHaveValue('4.89');
    expect(inputs[1]).toHaveValue('2.99');

    fireEvent.change(inputs[0]!, { target: { value: '5.25' } });
    expect(inputs[0]).toHaveValue('5.25');
    expect(inputs[1]).toHaveValue('2.99');
    fireEvent.click(screen.getAllByRole('button', { name: '定价' })[0]!);

    await waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        '/admin/catalog/stores/store-1/products/product-1/price',
        { method: 'PUT', body: { price_minor: 525 } },
      ),
    );
  });
});
