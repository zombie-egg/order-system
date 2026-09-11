import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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

  it('deletes an option group after explicit confirmation', async () => {
    const request = vi.fn(() => Promise.resolve(undefined));
    const optionGroups = [{
      id: 'group-1',
      store_id: 'store-1',
      code: 'size',
      translations: { 'nl-NL': 'Formaat' },
      sort_order: 0,
      active: true,
      values: [],
    }];
    const api = {
      get: vi.fn((path: string) => {
        if (path.endsWith('/products')) return Promise.resolve(products);
        if (path.endsWith('/option-groups')) return Promise.resolve(optionGroups);
        return Promise.resolve([]);
      }),
      request,
      post: vi.fn(),
      patch: vi.fn(),
    } as unknown as ApiClient;
    vi.spyOn(window, 'confirm').mockReturnValue(true);

    render(
      <AdminI18nProvider>
        <ProductsPricingPage api={api} stores={[store]} canWrite />
      </AdminI18nProvider>,
    );

    const groupSection = (await screen.findByDisplayValue('Formaat')).closest('section');
    expect(groupSection).not.toBeNull();
    fireEvent.click(within(groupSection!).getByRole('button', { name: '删除' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/admin/catalog/stores/store-1/option-groups/group-1',
      { method: 'DELETE' },
    ));
  });

  it('edits the complete selling price and sends the derived minor-unit delta', async () => {
    const request = vi.fn(() => Promise.resolve(undefined));
    const optionGroups = [{
      id: 'group-1', store_id: 'store-1', code: 'size',
      translations: { 'nl-NL': 'Formaat' }, sort_order: 0, active: true,
      values: [{
        id: 'large', code: 'large', translations: { 'nl-NL': 'Groot' },
        sort_order: 0, active: true,
      }],
    }];
    const productsWithOptions: AdminProductList = {
      ...products,
      products: [{
        ...products.products[0]!,
        option_rules: [{
          option_group_id: 'group-1', minimum_selections: 1, maximum_selections: 1,
          sort_order: 0, default_option_value_id: 'large',
        }],
        option_prices: { large: 50 },
      }],
    };
    const api = {
      get: vi.fn((path: string) => {
        if (path.endsWith('/products')) return Promise.resolve(productsWithOptions);
        if (path.endsWith('/option-groups')) return Promise.resolve(optionGroups);
        return Promise.resolve([]);
      }),
      request,
      post: vi.fn(),
      patch: vi.fn(),
    } as unknown as ApiClient;

    render(
      <AdminI18nProvider>
        <ProductsPricingPage api={api} stores={[store]} canWrite />
      </AdminI18nProvider>,
    );

    const input = await screen.findByRole('spinbutton', { name: 'Groot 规格售价' });
    expect(input).toHaveValue(5.39);
    fireEvent.change(input, { target: { value: '6.00' } });
    fireEvent.blur(input);

    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/admin/catalog/stores/store-1/products/product-1/options/large/price',
      { method: 'PUT', body: { price_delta_minor: 111 } },
    ));
  });
});
