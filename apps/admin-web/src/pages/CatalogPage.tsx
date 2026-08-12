import { useState, type FormEvent } from 'react';
import { catalogItemExample, type CatalogFormKind } from '../admin-contracts';
import type { ApiClient } from '../api';
import { Field, MutationMessage, PageHeader, SubmitButton } from '../components';
import { formNumber, formText } from '../form';
import {
  localInputToIso,
  parseJsonArray,
  parseJsonObject,
  parseMajorMoney,
  toLocalDateTimeInput,
} from '../format';
import type { ResourceCreated, StoreWithPolicy } from '../types';

type FormKind = CatalogFormKind;

export function CatalogPage({
  api,
  stores,
  assignedStoreIds,
  canTenantWrite,
  canStoreWrite,
}: {
  api: ApiClient;
  stores: StoreWithPolicy[];
  assignedStoreIds: string[];
  canTenantWrite: boolean;
  canStoreWrite: boolean;
}) {
  const firstWritableKind: FormKind | null = canTenantWrite
    ? 'category'
    : canStoreWrite
      ? 'price-book'
      : null;
  const [kind, setKind] = useState<FormKind>(firstWritableKind ?? 'category');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [validityWarning, setValidityWarning] = useState<string | null>(null);

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    setPending(true);
    setError(null);
    setSuccess(null);
    let path = '';
    let payload: unknown;
    try {
      const storeId = formText(form, 'store_id');
      if (kind === 'category') {
        path = '/admin/catalog/categories';
        payload = {
          store_id: storeId,
          code: formText(form, 'code'),
          translations: { [formText(form, 'locale')]: formText(form, 'name') },
          sort_order: formNumber(form, 'sort_order'),
        };
      } else if (kind === 'option-group') {
        path = '/admin/catalog/option-groups';
        payload = {
          store_id: storeId,
          code: formText(form, 'code'),
          translations: { [formText(form, 'locale')]: formText(form, 'name') },
          sort_order: formNumber(form, 'sort_order'),
          values: parseJsonArray(formText(form, 'items'), 'Option values'),
        };
      } else if (kind === 'product') {
        path = '/admin/catalog/products';
        payload = {
          store_id: storeId,
          category_id: formText(form, 'category_id'),
          sku: formText(form, 'code'),
          tax_category_code: formText(form, 'tax_category_code'),
          image_url: formText(form, 'image_url') || null,
          translations: {
            [formText(form, 'locale')]: {
              name: formText(form, 'name'),
              description: formText(form, 'description'),
            },
          },
          preparation_data: parseJsonObject(formText(form, 'preparation_data'), 'Preparation data'),
          allergen_data: parseJsonObject(formText(form, 'allergen_data'), 'Allergen data'),
          sort_order: formNumber(form, 'sort_order'),
          option_rules: parseJsonArray(formText(form, 'items'), 'Option rules'),
        };
      } else if (kind === 'price-book') {
        path = '/admin/catalog/price-books';
        payload = {
          store_id: storeId,
          code: formText(form, 'code'),
          version: formNumber(form, 'version'),
          currency: formText(form, 'currency'),
          prices_include_tax: true,
          valid_from: localInputToIso(formText(form, 'valid_from')),
          valid_to: null,
          items: parseJsonArray(formText(form, 'items'), 'Price book items'),
        };
      } else if (kind === 'tax-policy') {
        path = '/admin/pricing/tax-policies';
        payload = {
          store_id: storeId,
          version: formNumber(form, 'version'),
          rounding_mode: 'HALF_UP',
          rounding_scope: 'LINE',
          valid_from: localInputToIso(formText(form, 'valid_from')),
          valid_to: null,
          rates: parseJsonArray(formText(form, 'items'), 'Tax rates'),
        };
      } else {
        path = '/admin/pricing/promotions';
        const type = formText(form, 'promotion_type');
        const rawValue = formText(form, 'value');
        payload = {
          store_id: storeId,
          code: formText(form, 'code'),
          name: formText(form, 'name'),
          promotion_type: type,
          value:
            type === 'PERCENTAGE'
              ? Math.round(Number(rawValue) * 10_000)
              : parseMajorMoney(rawValue),
          minimum_total_minor: parseMajorMoney(formText(form, 'minimum_total')),
          starts_at: localInputToIso(formText(form, 'valid_from')),
          ends_at: null,
        };
      }
    } catch (reason) {
      setPending(false);
      setError(reason);
      return;
    }
    void api.post<ResourceCreated>(path, payload).then(
      (created) => {
        setPending(false);
        setSuccess(`${kind.replaceAll('-', ' ')} created: ${created.id}`);
        form.reset();
      },
      (reason: unknown) => {
        setPending(false);
        setError(reason);
      },
    );
  };

  const now = toLocalDateTimeInput(new Date());
  const itemExample = catalogItemExample(kind);
  const options: { value: FormKind; label: string; enabled: boolean }[] = [
    { value: 'category', label: 'Category', enabled: canTenantWrite },
    { value: 'option-group', label: 'Option group', enabled: canTenantWrite },
    { value: 'product', label: 'Product', enabled: canTenantWrite },
    { value: 'price-book', label: 'Price book', enabled: canStoreWrite },
    { value: 'tax-policy', label: 'Tax policy', enabled: canTenantWrite },
    { value: 'promotion', label: 'Promotion', enabled: canStoreWrite },
  ];
  const namedStoreIds = new Set(stores.map(({ store }) => store.id));
  const unnamedStoreIds = assignedStoreIds.filter((storeId) => !namedStoreIds.has(storeId));
  return (
    <section>
      <PageHeader
        title="Catalog and pricing setup"
        description="Functional creation forms use the exact backend request shapes. JSON fields support advanced domain structures without adding UI dependencies."
      />
      <div className="tab-list" role="tablist" aria-label="Resource type">
        {options
          .filter((option) => option.enabled)
          .map((option) => (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={kind === option.value}
              className={kind === option.value ? 'active' : ''}
              onClick={() => {
                setKind(option.value);
                setValidityWarning(null);
              }}
            >
              {option.label}
            </button>
          ))}
      </div>
      <MutationMessage error={error} success={success} />
      {!firstWritableKind ? (
        <div className="notice notice-info">
          This account can read the catalog but cannot change catalog or pricing resources.
        </div>
      ) : null}
      {firstWritableKind ? (
        <form key={kind} className="card form-grid" onSubmit={submit}>
          <Field label="Store" htmlFor="catalog_store">
            <select id="catalog_store" name="store_id" required defaultValue="">
              <option value="" disabled>
                Select a store
              </option>
              {stores.map(({ store }) => (
                <option key={store.id} value={store.id}>
                  {store.name}
                </option>
              ))}
              {unnamedStoreIds.map((storeId) => (
                <option key={storeId} value={storeId}>
                  Assigned store {storeId.slice(0, 8)}
                </option>
              ))}
            </select>
          </Field>
          {kind !== 'tax-policy' ? (
            <Field label="Code / SKU" htmlFor="catalog_code">
              <input id="catalog_code" name="code" required />
            </Field>
          ) : null}
          {['category', 'option-group', 'product', 'promotion'].includes(kind) ? (
            <Field label="Name" htmlFor="catalog_name">
              <input id="catalog_name" name="name" required />
            </Field>
          ) : null}
          {['category', 'option-group', 'product'].includes(kind) ? (
            <>
              <Field label="Locale" htmlFor="catalog_locale">
                <input id="catalog_locale" name="locale" defaultValue="nl-NL" required />
              </Field>
              <Field label="Sort order" htmlFor="sort_order">
                <input
                  id="sort_order"
                  name="sort_order"
                  type="number"
                  min="0"
                  defaultValue="0"
                  required
                />
              </Field>
            </>
          ) : null}
          {kind === 'product' ? (
            <>
              <Field label="Category ID" htmlFor="category_id">
                <input id="category_id" name="category_id" required />
              </Field>
              <Field label="Tax category code" htmlFor="tax_category_code">
                <input
                  id="tax_category_code"
                  name="tax_category_code"
                  defaultValue="STANDARD"
                  required
                />
              </Field>
              <Field label="Image URL" htmlFor="image_url">
                <input id="image_url" name="image_url" type="url" />
              </Field>
              <Field label="Description" htmlFor="description">
                <textarea id="description" name="description" />
              </Field>
              <Field label="Preparation JSON" htmlFor="preparation_data">
                <textarea id="preparation_data" name="preparation_data" defaultValue="{}" />
              </Field>
              <Field label="Allergen JSON" htmlFor="allergen_data">
                <textarea id="allergen_data" name="allergen_data" defaultValue="{}" />
              </Field>
            </>
          ) : null}
          {['price-book', 'tax-policy'].includes(kind) ? (
            <Field label="Version" htmlFor="catalog_version">
              <input
                id="catalog_version"
                name="version"
                type="number"
                min="1"
                defaultValue="2"
                required
              />
            </Field>
          ) : null}
          {kind === 'price-book' ? (
            <Field label="Currency" htmlFor="catalog_currency">
              <input
                id="catalog_currency"
                name="currency"
                minLength={3}
                maxLength={3}
                defaultValue="EUR"
                required
              />
            </Field>
          ) : null}
          {['price-book', 'tax-policy', 'promotion'].includes(kind) ? (
            <Field label={kind === 'promotion' ? 'Starts at' : 'Valid from'} htmlFor="valid_from">
              <input
                id="valid_from"
                name="valid_from"
                type="datetime-local"
                defaultValue={now}
                required
              />
            </Field>
          ) : null}
          {['price-book', 'tax-policy'].includes(kind) ? (
            <div className="notice notice-warning">
              The Backend publishes this resource immediately with an open-ended interval. If the
              store already has a published {kind === 'price-book' ? 'price book' : 'tax policy'},
              creation is expected to be rejected until a future replacement endpoint can close the
              current interval.
            </div>
          ) : null}
          {kind === 'promotion' ? (
            <>
              <Field label="Promotion type" htmlFor="promotion_type">
                <select id="promotion_type" name="promotion_type">
                  <option>PERCENTAGE</option>
                  <option>FIXED_AMOUNT</option>
                </select>
              </Field>
              <Field
                label="Value"
                htmlFor="promotion_value"
                hint="Percent for percentage promotions, euros for fixed amount."
              >
                <input id="promotion_value" name="value" inputMode="decimal" required />
              </Field>
              <Field label="Minimum order total (EUR)" htmlFor="minimum_total">
                <input
                  id="minimum_total"
                  name="minimum_total"
                  defaultValue="0.00"
                  inputMode="decimal"
                  required
                />
              </Field>
            </>
          ) : null}
          {['option-group', 'product', 'price-book', 'tax-policy'].includes(kind) ? (
            <Field
              label={
                kind === 'option-group'
                  ? 'Option values JSON'
                  : kind === 'product'
                    ? 'Option rules JSON'
                    : kind === 'price-book'
                      ? 'Price items JSON'
                      : 'Tax rates JSON'
              }
              htmlFor="catalog_items"
              hint="Must be a JSON array matching the backend schema."
            >
              <textarea
                id="catalog_items"
                name="items"
                rows={8}
                defaultValue={itemExample}
                required
              />
            </Field>
          ) : null}
          {validityWarning ? <div className="notice notice-warning">{validityWarning}</div> : null}
          {['price-book', 'tax-policy'].includes(kind) ? (
            <button
              type="button"
              className="button button-primary"
              disabled={pending}
              onClick={() =>
                setValidityWarning(
                  'Confirm the store has no overlapping published interval, then submit again.',
                )
              }
            >
              Review publishing constraint
            </button>
          ) : (
            <SubmitButton pending={pending}>Create {kind.replaceAll('-', ' ')}</SubmitButton>
          )}
          {validityWarning ? (
            <SubmitButton pending={pending}>Create {kind.replaceAll('-', ' ')}</SubmitButton>
          ) : null}
        </form>
      ) : null}
    </section>
  );
}
