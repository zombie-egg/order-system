import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { CatalogProduct } from './types';
import { ProductCustomizer } from './ProductCustomizer';

const product: CatalogProduct = {
  id: 'tea-1', sku: 'TEA-1', name: 'Thee', description: '', image_url: null,
  price_minor: 1000, currency: 'EUR', tax_category_code: 'VAT_STANDARD', allergen_data: {},
  option_groups: [{
    id: 'size', code: 'size', name: 'Formaat', minimum_selections: 1, maximum_selections: 1,
    values: [
      { id: 'small', code: 'small', name: 'Klein', price_delta_minor: 0, active: true, is_default: true },
      { id: 'medium', code: 'medium', name: 'Middel', price_delta_minor: 100, active: true },
      { id: 'large', code: 'large', name: 'Groot', price_delta_minor: 200, active: true },
    ],
  }],
};

describe('ProductCustomizer', () => {
  it('shows the complete price for each variant and updates the selected total', () => {
    const onAdd = vi.fn();
    render(
      <ProductCustomizer
        product={product}
        locale="nl-NL"
        language="nl-NL"
        onCancel={vi.fn()}
        onAdd={onAdd}
      />,
    );

    expect(screen.getAllByText(/€\s*10,00/)).toHaveLength(2);
    expect(screen.getByText(/€\s*11,00/)).toBeInTheDocument();
    expect(screen.getByText(/€\s*12,00/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('radio', { name: /Groot/ }));
    const addButton = screen.getByRole('button', { name: /Toevoegen.*€\s*12,00/ });
    fireEvent.click(addButton);
    expect(onAdd).toHaveBeenCalledWith(['large']);
  });
});
