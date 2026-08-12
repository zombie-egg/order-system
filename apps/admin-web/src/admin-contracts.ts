export const STAFF_ROLE_CODES = ['manager', 'staff', 'reviewer', 'owner'] as const;

export type CatalogFormKind =
  'category' | 'option-group' | 'product' | 'price-book' | 'tax-policy' | 'promotion';

export function catalogItemExample(kind: CatalogFormKind): string {
  if (kind === 'option-group') {
    return '[\n  {\n    "code": "extra-shot",\n    "translations": { "nl-NL": "Extra shot" },\n    "sort_order": 0\n  }\n]';
  }
  if (kind === 'price-book') {
    return '[\n  {\n    "product_id": "paste-product-uuid",\n    "price_minor": 350,\n    "option_prices": []\n  }\n]';
  }
  if (kind === 'tax-policy') {
    return '[\n  {\n    "tax_category_code": "non_alcoholic_beverage",\n    "rate_ppm": 90000\n  }\n]';
  }
  return '[]';
}

const ADMIN_NAVIGATION = [
  { label: 'Overview', permissions: ['report:read'] },
  { label: 'Stores', permissions: ['organization:read'] },
  { label: 'Staff', permissions: ['identity:read'] },
  {
    label: 'Catalog & pricing',
    permissions: ['catalog:read', 'catalog:write', 'catalog:tenant_write'],
  },
  { label: 'Orders', permissions: ['order:read'] },
  { label: 'Refunds', permissions: ['payment:read'] },
  { label: 'Manual review', permissions: ['review:read'] },
  { label: 'Reports', permissions: ['report:read'] },
  { label: 'Audit', permissions: ['audit:read'] },
] as const;

export function navigationLabelsForPermissions(permissions: Iterable<string>): string[] {
  const available = permissions instanceof Set ? permissions : new Set(permissions);
  return ADMIN_NAVIGATION.filter((item) =>
    item.permissions.some((permission) => available.has(permission)),
  ).map((item) => item.label);
}
