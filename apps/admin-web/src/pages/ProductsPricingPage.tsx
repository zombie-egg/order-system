import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
import { EmptyState, ErrorState, Field, LoadingState, MutationMessage, PageHeader, StatusBadge, SubmitButton } from '../components';
import { formatMoneyMinor, parseMajorMoney, resizeImageToDataUrl } from '../format';
import { useAdminI18n } from '../i18n';
import type { AdminCategory, AdminOptionGroup, AdminProduct, AdminProductList, StoreWithPolicy } from '../types';

interface Props {
  api: ApiClient;
  stores: StoreWithPolicy[];
  canWrite: boolean;
}

interface EditDraft {
  id: string;
  name: string;
  description: string;
  category_id: string;
  status: string;
  active: boolean;
  optionGroupIds: string[];
  defaultValueIds: Record<string, string>;
}

export function ProductsPricingPage({ api, stores, canWrite }: Props) {
  const { choose } = useAdminI18n();
  const [storeId, setStoreId] = useState(stores[0]?.store.id ?? '');
  const [result, setResult] = useState<AdminProductList | null>(null);
  const [categories, setCategories] = useState<AdminCategory[]>([]);
  const [optionGroups, setOptionGroups] = useState<AdminOptionGroup[]>([]);
  const [newGroupName, setNewGroupName] = useState('');
  const [newGroupValues, setNewGroupValues] = useState('');
  const [newValueNames, setNewValueNames] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [priceValues, setPriceValues] = useState<Record<string, string>>({});
  const [editImage, setEditImage] = useState<string | null>(null);
  const [editImagePreview, setEditImagePreview] = useState<string | null>(null);

  const selectedStore = useMemo(
    () => stores.find(({ store }) => store.id === storeId)?.store,
    [storeId, stores],
  );
  const locale = selectedStore?.locale ?? 'nl-NL';

  const load = useCallback(async () => {
    if (!storeId) return;
    setLoading(true);
    setError(null);
    try {
      const [list, cats, groups] = await Promise.all([
        api.get<AdminProductList>(`/admin/catalog/stores/${storeId}/products`),
        api.get<AdminCategory[]>(`/admin/catalog/stores/${storeId}/categories`),
        api.get<AdminOptionGroup[]>(`/admin/catalog/stores/${storeId}/option-groups`),
      ]);
      setResult(list);
      setCategories(cats);
      setOptionGroups(groups);
      setPriceValues(
        Object.fromEntries(
          list.products.map((product) => [
            product.id,
            product.price_minor === null ? '' : (product.price_minor / 100).toFixed(2),
          ]),
        ),
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, storeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const openEdit = (product: AdminProduct) => {
    setDraft({
      id: product.id,
      name: product.name,
      description: product.description,
      category_id: product.category_id ?? '',
      status: product.status,
      active: product.active,
      optionGroupIds: (product.option_rules ?? []).map((rule) => rule.option_group_id),
      defaultValueIds: Object.fromEntries(
        (product.option_rules ?? []).map((rule) => [rule.option_group_id, rule.default_option_value_id ?? '']),
      ),
    });
    setEditImage(product.image_url);
    setEditImagePreview(product.image_url);
  };

  const handleEditImage = async (file: File | undefined) => {
    if (!file) return;
    const dataUrl = await resizeImageToDataUrl(file);
    setEditImagePreview(dataUrl);
    setBusy('image');
    setError(null);
    try {
      const res = await api.post<{ image_url: string }>('/admin/catalog/product-images', {
        image_data: dataUrl,
      });
      setEditImage(res.image_url);
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const saveEdit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft) return;
    const body: Record<string, unknown> = {
      translations: {
        'nl-NL': { name: draft.name, description: draft.description },
        'zh-CN': { name: draft.name, description: draft.description },
      },
      category_id: draft.category_id || undefined,
      status: draft.status,
      active: draft.active,
      option_rules: draft.optionGroupIds.map((groupId, index) => ({
        option_group_id: groupId,
        minimum_selections: 1,
        maximum_selections: 1,
        sort_order: index,
        default_option_value_id: draft.defaultValueIds[groupId] || null,
      })),
    };
    if (editImage !== undefined) body.image_url = editImage;
    setBusy('save');
    setError(null);
    setMessage(null);
    try {
      await api.patch(`/admin/catalog/stores/${storeId}/products/${draft.id}`, body);
      setMessage(choose('商品信息已更新。', 'Productinformatie bijgewerkt.'));
      setDraft(null);
      setEditImage(null);
      setEditImagePreview(null);
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const savePrice = async (product: AdminProduct) => {
    let minor: number;
    try {
      minor = parseMajorMoney(priceValues[product.id] ?? '');
    } catch {
      setError(choose('请输入有效的价格（最多两位小数）。', 'Voer een geldige prijs in (max. 2 decimalen).'));
      return;
    }
    setBusy(`price-${product.id}`);
    setError(null);
    setMessage(null);
    try {
      await api.request(`/admin/catalog/stores/${storeId}/products/${product.id}/price`, {
        method: 'PUT',
        body: { price_minor: minor },
      });
      setMessage(choose('价格已保存。', 'Prijs opgeslagen.'));
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const createGroup = async () => {
    const values = newGroupValues.split(',').map((value) => value.trim()).filter(Boolean);
    if (!newGroupName.trim() || values.length === 0) return;
    setBusy('new-option-group');
    setError(null);
    try {
      await api.post('/admin/catalog/option-groups', {
        store_id: storeId,
        code: newGroupName.toLowerCase().replace(/[^a-z0-9]+/g, '-') || `option-${Date.now()}`,
        translations: { 'nl-NL': newGroupName.trim(), 'zh-CN': newGroupName.trim() },
        sort_order: optionGroups.length,
        values: values.map((name, index) => ({
          code: name.toLowerCase().replace(/[^a-z0-9]+/g, '-') || `value-${index + 1}`,
          translations: { 'nl-NL': name, 'zh-CN': name },
          sort_order: index,
          active: true,
        })),
      });
      setNewGroupName('');
      setNewGroupValues('');
      await load();
      setMessage(choose('规格组已创建。', 'Optiegroep aangemaakt.'));
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const updateGroup = async (group: AdminOptionGroup, values: Record<string, unknown>) => {
    setBusy(`group-${group.id}`);
    try {
      await api.patch(`/admin/catalog/stores/${storeId}/option-groups/${group.id}`, values);
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const updateValue = async (groupId: string, valueId: string, values: Record<string, unknown>) => {
    setBusy(`value-${valueId}`);
    try {
      await api.patch(`/admin/catalog/stores/${storeId}/option-groups/${groupId}/values/${valueId}`, values);
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const addValue = async (groupId: string) => {
    const name = newValueNames[groupId]?.trim();
    if (!name) return;
    setBusy(`add-${groupId}`);
    try {
      await api.post(`/admin/catalog/stores/${storeId}/option-groups/${groupId}/values`, {
        code: name.toLowerCase().replace(/[^a-z0-9]+/g, '-') || `value-${Date.now()}`,
        translations: { 'nl-NL': name, 'zh-CN': name },
        sort_order: optionGroups.find((group) => group.id === groupId)?.values.length ?? 0,
        active: true,
      });
      setNewValueNames((current) => ({ ...current, [groupId]: '' }));
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const saveOptionPrice = async (product: AdminProduct, valueId: string, raw: string) => {
    let priceDelta: number;
    try {
      priceDelta = parseMajorMoney(raw);
    } catch {
      setError(choose('请输入有效的规格加价。', 'Voer een geldige optietoeslag in.'));
      return;
    }
    setBusy(`option-price-${product.id}-${valueId}`);
    try {
      await api.request(`/admin/catalog/stores/${storeId}/products/${product.id}/options/${valueId}/price`, {
        method: 'PUT',
        body: { price_delta_minor: priceDelta },
      });
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const toggleAvailability = async (product: AdminProduct) => {
    setBusy(`avail-${product.id}`);
    setError(null);
    try {
      await api.patch(`/admin/catalog/stores/${storeId}/products/${product.id}/availability`, {
        available: !product.available,
        expected_version: product.version,
      });
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const deleteProduct = async (product: AdminProduct) => {
    if (
      !window.confirm(
        choose(
          `确定要删除商品「${product.name}」吗？此操作会把它从菜单中移除。`,
          `Weet je zeker dat je “${product.name}” wilt verwijderen? Het wordt uit het menu gehaald.`,
        ),
      )
    ) {
      return;
    }
    setBusy(`del-${product.id}`);
    setError(null);
    setMessage(null);
    try {
      await api.request(`/admin/catalog/stores/${storeId}/products/${product.id}`, {
        method: 'DELETE',
      });
      setMessage(choose('商品已删除。', 'Product verwijderd.'));
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(null);
    }
  };

  const currency = result?.currency ?? selectedStore?.currency ?? 'EUR';

  return (
    <section>
      <PageHeader
        title={choose('商品与定价', 'Assortiment en prijzen')}
        description={choose(
          '查看并编辑现有商品信息，设置价格，控制门店可售状态。',
          'Bekijk en bewerk bestaande producten, stel prijzen in en beheer de beschikbaarheid.',
        )}
      />
      <div className="card form-grid">
        <Field label={choose('门店', 'Vestiging')} htmlFor="pp-store">
          <select id="pp-store" value={storeId} onChange={(e) => setStoreId(e.target.value)}>
            {stores.map(({ store }) => (
              <option key={store.id} value={store.id}>
                {store.name} · {store.code}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <article className="card">
        <header className="card-header">
          <div>
            <h2>{choose('商品规格', 'Productopties')}</h2>
            <p>{choose('管理该门店的规格组、规格值、排序与启用状态。', 'Beheer optiegroepen, waarden, volgorde en beschikbaarheid voor deze vestiging.')}</p>
          </div>
        </header>
        <div className="form-grid option-create-grid">
          <Field label={choose('规格组名称', 'Naam optiegroep')} htmlFor="pp-new-group">
            <input id="pp-new-group" value={newGroupName} onChange={(event) => setNewGroupName(event.target.value)} placeholder={choose('例如：杯型', 'Bijv. Formaat')} />
          </Field>
          <Field label={choose('规格值（逗号分隔）', 'Waarden (komma-gescheiden)')} htmlFor="pp-new-values">
            <input id="pp-new-values" value={newGroupValues} onChange={(event) => setNewGroupValues(event.target.value)} placeholder={choose('小杯, 中杯, 大杯', 'Klein, Middel, Groot')} />
          </Field>
          <button type="button" className="button" disabled={!canWrite || busy === 'new-option-group'} onClick={() => void createGroup()}>
            {busy === 'new-option-group' ? '…' : choose('新建规格组', 'Optiegroep maken')}
          </button>
        </div>
        <div className="option-admin-list">
          {optionGroups.map((group) => (
            <section className="option-admin-group" key={group.id}>
              <div className="option-admin-heading">
                <input
                  aria-label={choose('规格组名称', 'Naam optiegroep')}
                  defaultValue={group.translations['nl-NL'] ?? group.code}
                  onBlur={(event) => {
                    const name = event.currentTarget.value.trim();
                    if (name && name !== (group.translations['nl-NL'] ?? group.code)) {
                      void updateGroup(group, { translations: { 'nl-NL': name, 'zh-CN': name } });
                    }
                  }}
                  disabled={!canWrite}
                />
                <input type="number" min="0" aria-label={choose('排序', 'Volgorde')} defaultValue={group.sort_order} onBlur={(event) => void updateGroup(group, { sort_order: Number(event.currentTarget.value) })} disabled={!canWrite} />
                <label className="check-field">
                  <input type="checkbox" checked={group.active} onChange={() => void updateGroup(group, { active: !group.active })} disabled={!canWrite} />
                  {choose('启用', 'Actief')}
                </label>
              </div>
              <div className="option-value-list">
                {group.values.map((value) => (
                  <div key={value.id}>
                    <input
                      defaultValue={value.translations['nl-NL'] ?? value.code}
                      aria-label={choose('规格值名称', 'Naam optiewaarde')}
                      onBlur={(event) => {
                        const name = event.currentTarget.value.trim();
                        if (name && name !== (value.translations['nl-NL'] ?? value.code)) {
                          void updateValue(group.id, value.id, { translations: { 'nl-NL': name, 'zh-CN': name } });
                        }
                      }}
                      disabled={!canWrite}
                    />
                    <input type="number" min="0" defaultValue={value.sort_order} aria-label={choose('排序', 'Volgorde')} onBlur={(event) => void updateValue(group.id, value.id, { sort_order: Number(event.currentTarget.value) })} disabled={!canWrite} />
                    <label className="check-field"><input type="checkbox" checked={value.active} onChange={() => void updateValue(group.id, value.id, { active: !value.active })} disabled={!canWrite} />{choose('启用', 'Actief')}</label>
                  </div>
                ))}
                <div>
                  <input value={newValueNames[group.id] ?? ''} onChange={(event) => setNewValueNames((current) => ({ ...current, [group.id]: event.target.value }))} placeholder={choose('新规格值', 'Nieuwe waarde')} />
                  <button type="button" className="button button-secondary" onClick={() => void addValue(group.id)} disabled={!canWrite || busy === `add-${group.id}`}>{choose('添加', 'Toevoegen')}</button>
                </div>
              </div>
            </section>
          ))}
        </div>
      </article>

      {loading ? (
        <LoadingState label={choose('正在加载商品…', 'Producten laden…')} />
      ) : error && !result ? (
        <ErrorState error={error} retry={() => void load()} />
      ) : (
        <article className="card">
          <header className="card-header">
            <div>
              <h2>{choose('商品列表', 'Producten')}</h2>
              <p>
                {choose(
                  `共 ${result?.products.length ?? 0} 个商品 · 币种 ${currency}`,
                  `${result?.products.length ?? 0} product(en) · valuta ${currency}`,
                )}
              </p>
            </div>
          </header>
          <MutationMessage error={error} success={message} />

          {!result || result.products.length === 0 ? (
            <EmptyState
              title={choose('还没有商品', 'Nog geen producten')}
              detail={choose('在「商品添加」中添加第一个商品。', 'Voeg het eerste product toe in “Product toevoegen”.')}
            />
          ) : (
            <ul className="catalog-list">
              {result.products.map((product) => (
                <li key={product.id} className="catalog-row">
                  <div className="catalog-thumb">
                    {product.image_url ? (
                      <img src={product.image_url} alt="" />
                    ) : (
                      <span aria-hidden="true">☕</span>
                    )}
                  </div>
                  <div className="catalog-info">
                    <strong>{product.name}</strong>
                    <small>
                      {product.category_name ?? choose('无分类', 'Geen categorie')} · {product.sku}
                    </small>
                    <small>
                      <StatusBadge value={product.status} />{' '}
                      {product.available ? choose('可售', 'Beschikbaar') : choose('停售', 'Niet beschikbaar')}
                    </small>
                  </div>
                  <div className="catalog-price">
                    <strong>{formatMoneyMinor(product.price_minor ?? 0, currency, locale)}</strong>
                    <input
                      value={priceValues[product.id] ?? ''}
                      onChange={(e) =>
                        setPriceValues((current) => ({ ...current, [product.id]: e.target.value }))
                      }
                      placeholder={choose('价格 €', 'Prijs €')}
                      disabled={!canWrite || busy === `price-${product.id}`}
                      onBlur={() => void savePrice(product)}
                      type="text"
                      inputMode="decimal"
                    />
                    <button
                      type="button"
                      className="button button-secondary"
                      disabled={!canWrite || busy === `price-${product.id}`}
                      onClick={() => void savePrice(product)}
                    >
                      {busy === `price-${product.id}` ? '…' : choose('定价', 'Prijs')}
                    </button>
                  </div>
                  {(product.option_rules ?? []).length > 0 && (
                    <div className="catalog-option-prices">
                      {(product.option_rules ?? []).flatMap((rule) => {
                        const group = optionGroups.find((entry) => entry.id === rule.option_group_id);
                        if (!group) return [];
                        return group.values.map((value) => (
                          <label key={value.id}>
                            <span>{group.translations['nl-NL'] ?? group.code}: {value.translations['nl-NL'] ?? value.code}</span>
                            <input
                              type="number"
                              step="0.01"
                              defaultValue={(((product.option_prices ?? {})[value.id] ?? 0) / 100).toFixed(2)}
                              aria-label={`${value.translations['nl-NL'] ?? value.code} ${choose('加价', 'toeslag')}`}
                              onBlur={(event) => void saveOptionPrice(product, value.id, event.currentTarget.value)}
                              disabled={!canWrite}
                            />
                          </label>
                        ));
                      })}
                    </div>
                  )}
                  <div className="catalog-actions">
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => openEdit(product)}
                      disabled={!canWrite}
                    >
                      {choose('编辑', 'Bewerken')}
                    </button>
                    <button
                      type="button"
                      className="button button-secondary"
                      disabled={busy === `avail-${product.id}`}
                      onClick={() => void toggleAvailability(product)}
                    >
                      {product.available ? choose('停售', 'Uitschakelen') : choose('上架', 'Beschikbaar')}
                    </button>
                    <button
                      type="button"
                      className="button button-secondary"
                      disabled={!canWrite || busy === `del-${product.id}`}
                      onClick={() => void deleteProduct(product)}
                    >
                      {busy === `del-${product.id}` ? '…' : choose('删除', 'Verwijderen')}
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </article>
      )}

      {draft && (
        <div className="dialog-backdrop" role="presentation">
          <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="pp-edit-title">
            <h2 id="pp-edit-title">{choose('编辑商品', 'Product bewerken')}</h2>
            <form className="form-grid" onSubmit={(event) => void saveEdit(event)}>
              <Field label={`${choose('商品名称', 'Productnaam')} *`} htmlFor="pp-name">
                <input
                  id="pp-name"
                  required
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                />
              </Field>
              <Field label={choose('简介', 'Beschrijving')} htmlFor="pp-desc">
                <textarea
                  id="pp-desc"
                  rows={3}
                  value={draft.description}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                />
              </Field>
              <Field label={choose('分类', 'Categorie')} htmlFor="pp-cat">
                <select
                  id="pp-cat"
                  value={draft.category_id}
                  onChange={(e) => setDraft({ ...draft, category_id: e.target.value })}
                >
                  <option value="">{choose('无分类', 'Geen categorie')}</option>
                  {categories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label={choose('状态', 'Status')} htmlFor="pp-status">
                <select
                  id="pp-status"
                  value={draft.status}
                  onChange={(e) => setDraft({ ...draft, status: e.target.value })}
                >
                  <option value="PUBLISHED">{choose('发布', 'Gepubliceerd')}</option>
                  <option value="DRAFT">{choose('草稿', 'Concept')}</option>
                </select>
              </Field>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={draft.active}
                  onChange={(e) => setDraft({ ...draft, active: e.target.checked })}
                />
                <span>{choose('启用商品', 'Product actief')}</span>
              </label>
              <Field label={choose('绑定规格组', 'Optiegroepen koppelen')} htmlFor="pp-option-groups">
                <div id="pp-option-groups" className="store-check-list">
                  {optionGroups.map((group) => {
                    const selected = draft.optionGroupIds.includes(group.id);
                    return (
                      <div key={group.id}>
                        <label>
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => setDraft({
                              ...draft,
                              optionGroupIds: selected
                                ? draft.optionGroupIds.filter((id) => id !== group.id)
                                : [...draft.optionGroupIds, group.id],
                            })}
                          />
                          {group.translations['nl-NL'] ?? group.code}
                        </label>
                        {selected && (
                          <select
                            aria-label={`${group.translations['nl-NL'] ?? group.code} ${choose('默认值', 'standaardwaarde')}`}
                            value={draft.defaultValueIds[group.id] ?? ''}
                            onChange={(event) => setDraft({
                              ...draft,
                              defaultValueIds: { ...draft.defaultValueIds, [group.id]: event.target.value },
                            })}
                          >
                            <option value="">{choose('无默认值', 'Geen standaardwaarde')}</option>
                            {group.values.filter((value) => value.active).map((value) => (
                              <option key={value.id} value={value.id}>{value.translations['nl-NL'] ?? value.code}</option>
                            ))}
                          </select>
                        )}
                      </div>
                    );
                  })}
                </div>
              </Field>
              <Field label={choose('商品图片', 'Productafbeelding')} htmlFor="pp-image">
                <input
                  id="pp-image"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={busy === 'image'}
                  onChange={(event) => void handleEditImage(event.target.files?.[0])}
                />
              </Field>
              {editImagePreview && (
                <Field label={choose('图片预览', 'Voorbeeld')} htmlFor="pp-image-preview">
                  <img id="pp-image-preview" src={editImagePreview} alt="" className="product-image-preview" />
                </Field>
              )}
              <MutationMessage error={error} success={null} />
              <div className="dialog-actions">
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => {
                    setDraft(null);
                    setEditImage(null);
                    setEditImagePreview(null);
                  }}
                >
                  {choose('取消', 'Annuleren')}
                </button>
                <SubmitButton pending={busy === 'save'}>{choose('保存', 'Opslaan')}</SubmitButton>
              </div>
            </form>
          </section>
        </div>
      )}
    </section>
  );
}
