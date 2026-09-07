import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ApiClient } from '../api';
import { AdminI18nProvider } from '../i18n';
import type { StoreWithPolicy } from '../types';
import { ProductAddPage } from './ProductAddPage';

const store = {
  store: {
    id: 'store-1', code: 'AMS-01', name: 'Amsterdam Store', country_code: 'NL',
    currency: 'EUR', locale: 'nl-NL', timezone: 'Europe/Amsterdam', active: true, version: 1,
  },
  policy: {
    store_id: 'store-1', accepting_orders: true, max_open_tickets: 50,
    kds_heartbeat_seconds: 30, printer_fallback_enabled: false,
    takeaway_fee_enabled: false, takeaway_fee_minor: 0, version: 1,
  },
} satisfies StoreWithPolicy;

describe('ProductAddPage', () => {
  it('saves full variant selling prices as backend price deltas', async () => {
    const request = vi.fn(() => Promise.resolve(undefined));
    const api = {
      get: vi.fn((path: string) => {
        if (path.endsWith('/categories')) {
          return Promise.resolve([{ id: 'category-1', code: 'tea', name: 'Thee', sort_order: 0, active: true }]);
        }
        if (path.endsWith('/option-groups')) {
          return Promise.resolve([{
            id: 'group-1', store_id: 'store-1', code: 'size',
            translations: { 'nl-NL': 'Formaat' }, sort_order: 0, active: true,
            values: [
              { id: 'small', code: 'small', translations: { 'nl-NL': 'Klein' }, sort_order: 0, active: true },
              { id: 'large', code: 'large', translations: { 'nl-NL': 'Groot' }, sort_order: 1, active: true },
            ],
          }]);
        }
        return Promise.resolve([]);
      }),
      post: vi.fn((path: string) => {
        if (path === '/admin/catalog/products') return Promise.resolve({ id: 'product-new' });
        return Promise.resolve({ id: 'unused' });
      }),
      request,
      patch: vi.fn(),
    } as unknown as ApiClient;

    render(
      <AdminI18nProvider>
        <ProductAddPage api={api} stores={[store]} canWrite />
      </AdminI18nProvider>,
    );

    fireEvent.click(await screen.findByLabelText(/Formaat/));
    fireEvent.change(screen.getByLabelText('Klein 规格售价'), { target: { value: '10.00' } });
    fireEvent.change(screen.getByLabelText('Groot 规格售价'), { target: { value: '12.00' } });
    fireEvent.change(screen.getByLabelText(/商品名称/), { target: { value: 'Testthee' } });
    fireEvent.change(screen.getByLabelText('价格 (€)'), { target: { value: '10.00' } });
    fireEvent.click(screen.getByRole('button', { name: '保存商品' }));

    await waitFor(() => expect(request).toHaveBeenCalledWith(
      '/admin/catalog/stores/store-1/products/product-new/options/small/price',
      { method: 'PUT', body: { price_delta_minor: 0 } },
    ));
    expect(request).toHaveBeenCalledWith(
      '/admin/catalog/stores/store-1/products/product-new/options/large/price',
      { method: 'PUT', body: { price_delta_minor: 200 } },
    );
  });
});
