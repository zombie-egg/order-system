import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
import { Field, MutationMessage, PageHeader, SubmitButton } from '../components';
import { parseMajorMoney, resizeImageToDataUrl } from '../format';
import { useAdminI18n } from '../i18n';
import type { AdminCategory, AdminOptionGroup, StoreWithPolicy } from '../types';

interface Props {
  api: ApiClient;
  stores: StoreWithPolicy[];
  canWrite: boolean;
}

export function ProductAddPage({ api, stores, canWrite }: Props) {
  const { choose } = useAdminI18n();
  const [selectedStoreIds, setSelectedStoreIds] = useState<string[]>(
    stores.map(({ store }) => store.id),
  );
  const [categories, setCategories] = useState<AdminCategory[]>([]);
  const [categoryId, setCategoryId] = useState('');
  const [optionGroups, setOptionGroups] = useState<AdminOptionGroup[]>([]);
  const [selectedOptionGroupIds, setSelectedOptionGroupIds] = useState<string[]>([]);
  const [variantPrices, setVariantPrices] = useState<Record<string, string>>({});
  const [newOptionGroupName, setNewOptionGroupName] = useState('');
  const [newOptionValues, setNewOptionValues] = useState('');
  const [newCategoryName, setNewCategoryName] = useState('');
  const [addingCategory, setAddingCategory] = useState(false);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const primaryStoreId = selectedStoreIds[0] ?? '';
  const submittingRef = useRef(false);

  useEffect(() => {
    if (!primaryStoreId) return;
    setError(null);
    setSuccess(null);
    setCategoryId('');
    void api
      .get<AdminCategory[]>(`/admin/catalog/stores/${primaryStoreId}/categories`)
      .then((rows) => {
        setCategories(rows);
        const first = rows[0];
        if (first) setCategoryId(first.id);
      }, setError);
    void api
      .get<AdminOptionGroup[]>(`/admin/catalog/stores/${primaryStoreId}/option-groups`)
      .then(setOptionGroups, setError);
  }, [api, primaryStoreId]);

  const toggleStore = (storeId: string) => {
    setSelectedStoreIds((current) =>
      current.includes(storeId) ? current.filter((id) => id !== storeId) : [...current, storeId],
    );
  };

  const handleImage = async (file: File | undefined) => {
    if (!file) return;
    if (!/^image\/(jpeg|png|webp)$/.test(file.type)) {
      setError(choose('仅支持 JPG、PNG 或 WebP 图片。', 'Alleen JPG, PNG of WebP afbeeldingen.'));
      return;
    }
    setUploadingImage(true);
    setError(null);
    try {
      const dataUrl = await resizeImageToDataUrl(file);
      setImagePreview(dataUrl);
      const result = await api.post<{ image_url: string }>('/admin/catalog/product-images', {
        image_data: dataUrl,
      });
      setImageUrl(result.image_url);
    } catch (cause) {
      setError(cause);
    } finally {
      setUploadingImage(false);
    }
  };

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite || selectedStoreIds.length === 0 || !primaryStoreId) return;
    if (submittingRef.current) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const rawName = data.get('name');
    const name = typeof rawName === 'string' ? rawName.trim() : '';
    if (!name) return;
    submittingRef.current = true;
    setPending(true);
    setError(null);
    setSuccess(null);
    try {
      let targetCategoryId = categoryId;
      if (addingCategory && newCategoryName.trim()) {
        const newName = newCategoryName.trim();
        const categoryCode =
          newName
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, '-')
            .replace(/^-|-$/g, '') || `cat-${Date.now()}`;
        const createdCat = await api.post<{ id: string }>('/admin/catalog/categories', {
          store_id: primaryStoreId,
          code: categoryCode,
          translations: { 'nl-NL': newName, 'zh-CN': newName },
          sort_order: categories.length,
        });
        targetCategoryId = createdCat.id;
        setCategoryId(createdCat.id);
        setNewCategoryName('');
        setAddingCategory(false);
      }
      if (!targetCategoryId) {
        throw new Error(
          choose('请选择一个分类或新建一个分类。', 'Kies of maak eerst een categorie.'),
        );
      }
      const rawDescription = data.get('description');
      const rawPrice = data.get('price');
      const description = typeof rawDescription === 'string' ? rawDescription.trim() : '';
      const priceMajor = typeof rawPrice === 'string' ? rawPrice.trim() : '';
      const basePriceMinor = priceMajor ? parseMajorMoney(priceMajor) : 0;
      const selectedVariantPrices = optionGroups
        .filter((group) => selectedOptionGroupIds.includes(group.id))
        .flatMap((group) => group.values)
        .filter((value) => value.active && variantPrices[value.id]?.trim())
        .map((value) => ({
          valueId: value.id,
          priceMinor: parseMajorMoney(variantPrices[value.id]!),
        }));
      const createdProduct = await api.post<{ id: string }>('/admin/catalog/products', {
        store_ids: selectedStoreIds,
        category_id: targetCategoryId,
        sku: `AUTO-${Date.now()}`,
        tax_category_code: 'VAT_STANDARD',
        ...(imageUrl ? { image_url: imageUrl } : {}),
        translations: {
          'nl-NL': { name, description },
          'zh-CN': { name, description },
        },
        preparation_data: {},
        allergen_data: {},
        sort_order: 0,
        option_rules: selectedOptionGroupIds.map((optionGroupId, index) => ({
          option_group_id: optionGroupId,
          minimum_selections: 1,
          maximum_selections: 1,
          sort_order: index,
          default_option_value_id:
            optionGroups.find((group) => group.id === optionGroupId)?.values.find((value) => value.active)?.id ?? null,
        })),
        ...(priceMajor || selectedVariantPrices.length > 0 ? { price_minor: basePriceMinor } : {}),
      });
      await Promise.all(selectedVariantPrices.map(({ valueId, priceMinor }) => {
        return api.request(
          `/admin/catalog/stores/${primaryStoreId}/products/${createdProduct.id}/options/${valueId}/price`,
          {
            method: 'PUT',
            body: { price_delta_minor: priceMinor - basePriceMinor },
          },
        );
      }));
      setImageUrl(null);
      setImagePreview(null);
      setSelectedOptionGroupIds([]);
      setVariantPrices({});
      form.reset();
      setSuccess(
        choose(
          `商品已保存，已在 ${selectedStoreIds.length} 家门店上架。`,
          `Product opgeslagen en beschikbaar in ${selectedStoreIds.length} vestiging(en).`,
        ),
      );
      const rows = await api.get<AdminCategory[]>(
        `/admin/catalog/stores/${primaryStoreId}/categories`,
      );
      setCategories(rows);
    } catch (cause) {
      setError(cause);
    } finally {
      submittingRef.current = false;
      setPending(false);
    }
  };

  const createOptionGroup = async () => {
    if (!primaryStoreId || !newOptionGroupName.trim()) return;
    const values = newOptionValues.split(',').map((value) => value.trim()).filter(Boolean);
    if (values.length === 0) {
      setError(choose('请至少输入一个规格值。', 'Voer minimaal één optiewaarde in.'));
      return;
    }
    setPending(true);
    setError(null);
    try {
      const code = newOptionGroupName.toLowerCase().replace(/[^a-z0-9]+/g, '-') || `option-${Date.now()}`;
      const created = await api.post<{ id: string }>('/admin/catalog/option-groups', {
        store_id: primaryStoreId,
        code,
        translations: { 'nl-NL': newOptionGroupName.trim(), 'zh-CN': newOptionGroupName.trim() },
        sort_order: optionGroups.length,
        values: values.map((name, index) => ({
          code: name.toLowerCase().replace(/[^a-z0-9]+/g, '-') || `value-${index + 1}`,
          translations: { 'nl-NL': name, 'zh-CN': name },
          sort_order: index,
          active: true,
        })),
      });
      const rows = await api.get<AdminOptionGroup[]>(`/admin/catalog/stores/${primaryStoreId}/option-groups`);
      setOptionGroups(rows);
      setSelectedOptionGroupIds((current) => [...current, created.id]);
      setNewOptionGroupName('');
      setNewOptionValues('');
    } catch (cause) {
      setError(cause);
    } finally {
      setPending(false);
    }
  };

  return (
    <section>
      <PageHeader
        title={choose('商品添加', 'Product toevoegen')}
        description={choose(
          '勾选一家或多家门店，一次创建商品并在所有选中门店上架。',
          'Selecteer een of meer vestigingen om een product in één keer beschikbaar te maken.',
        )}
      />
      <div className="card form-grid">
        <Field
          label={choose('上架门店（可多选）', 'Vestigingen (meerdere mogelijk)')}
          htmlFor="pa-stores"
        >
          <div className="store-check-list" id="pa-stores">
            {stores.map(({ store }) => (
              <label key={store.id}>
                <input
                  type="checkbox"
                  checked={selectedStoreIds.includes(store.id)}
                  onChange={() => toggleStore(store.id)}
                  disabled={!canWrite}
                />
                {store.name} · {store.code}
              </label>
            ))}
          </div>
        </Field>
      </div>

      <article className="card">
        <header className="card-header">
          <div>
            <h2>{choose('添加商品', 'Product toevoegen')}</h2>
            <p>
              {choose(
                '分类与商品信息。带 * 为必填。',
                'Categorie en productinformatie. Velden met * zijn verplicht.',
              )}
            </p>
          </div>
        </header>

        <form className="form-grid" onSubmit={(event) => void save(event)}>
          <Field label={choose('分类', 'Categorie')} htmlFor="pa-category">
            <select
              id="pa-category"
              value={categoryId}
              onChange={(e) => setCategoryId(e.target.value)}
              disabled={addingCategory}
            >
              <option value="">{choose('选择分类…', 'Kies een categorie…')}</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </Field>

          {!addingCategory ? (
            <div className="field">
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setAddingCategory(true)}
                disabled={!canWrite}
              >
                ＋ {choose('新建分类', 'Nieuwe categorie')}
              </button>
            </div>
          ) : (
            <Field label={choose('新分类名称', 'Nieuwe categorienaam')} htmlFor="pa-newcat">
              <input
                id="pa-newcat"
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                placeholder={choose('输入新分类名称', 'Voer een categorienaam in')}
                autoFocus
              />
            </Field>
          )}
          {addingCategory && (
            <div className="field">
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setAddingCategory(false)}
              >
                {choose('取消', 'Annuleren')}
              </button>
            </div>
          )}

          <Field label={`${choose('商品名称', 'Productnaam')} *`} htmlFor="pa-name">
            <input id="pa-name" name="name" required maxLength={200} autoFocus={!addingCategory} />
          </Field>
          <Field label={choose('简介', 'Beschrijving')} htmlFor="pa-desc">
            <textarea id="pa-desc" name="description" maxLength={2000} rows={3} />
          </Field>

          <Field label={choose('商品规格（单选）', 'Productopties (één keuze)')} htmlFor="pa-options">
            <div id="pa-options" className="store-check-list">
              {optionGroups.map((group) => (
                <label key={group.id}>
                  <input
                    type="checkbox"
                    checked={selectedOptionGroupIds.includes(group.id)}
                    onChange={() => setSelectedOptionGroupIds((current) =>
                      current.includes(group.id)
                        ? current.filter((id) => id !== group.id)
                        : [...current, group.id])}
                    disabled={!canWrite || !group.active}
                  />
                  {group.translations['nl-NL'] ?? group.code} · {group.values.filter((value) => value.active).length} {choose('个值', 'waarden')}
                </label>
              ))}
            </div>
          </Field>
          {optionGroups
            .filter((group) => selectedOptionGroupIds.includes(group.id))
            .map((group) => (
              <Field
                key={group.id}
                label={`${group.translations['nl-NL'] ?? group.code} · ${choose('规格售价 (€)', 'Variantprijzen (€)')}`}
                htmlFor={`pa-variant-${group.id}`}
                hint={choose(
                  '填写顾客看到的实际售价；留空则使用商品基础价。',
                  'Vul de volledige verkoopprijs in; leeg gebruikt de basisprijs.',
                )}
              >
                <div id={`pa-variant-${group.id}`} className="store-check-list">
                  {group.values.filter((value) => value.active).map((value) => (
                    <label key={value.id}>
                      <span>{value.translations['nl-NL'] ?? value.code}</span>
                      <input
                        type="number"
                        min="0"
                        step="0.01"
                        inputMode="decimal"
                        value={variantPrices[value.id] ?? ''}
                        onChange={(event) => setVariantPrices((current) => ({
                          ...current,
                          [value.id]: event.target.value,
                        }))}
                        placeholder={choose('实际售价', 'Verkoopprijs')}
                        aria-label={`${value.translations['nl-NL'] ?? value.code} ${choose('规格售价', 'variantprijs')}`}
                        disabled={!canWrite}
                      />
                    </label>
                  ))}
                </div>
              </Field>
            ))}
          <Field label={choose('直接新建规格组', 'Nieuwe optiegroep maken')} htmlFor="pa-option-name">
            <input
              id="pa-option-name"
              value={newOptionGroupName}
              onChange={(event) => setNewOptionGroupName(event.target.value)}
              placeholder={choose('例如：杯型', 'Bijv. Formaat')}
            />
            <input
              value={newOptionValues}
              onChange={(event) => setNewOptionValues(event.target.value)}
              placeholder={choose('规格值用逗号分隔', 'Waarden gescheiden door komma’s')}
            />
            <button type="button" className="button button-secondary" onClick={() => void createOptionGroup()} disabled={pending || !canWrite}>
              {choose('创建并选择', 'Maken en selecteren')}
            </button>
          </Field>

          <Field
            label={`${choose('商品图片', 'Productafbeelding')} (JPG/PNG/WebP)`}
            htmlFor="pa-image"
            hint={choose(
              '上传后保存，顾客点餐界面会显示商品图片。',
              'Na upload wordt deze afbeelding in het bestelmenu getoond.',
            )}
          >
            <input
              id="pa-image"
              type="file"
              accept="image/jpeg,image/png,image/webp"
              disabled={uploadingImage}
              onChange={(event) => void handleImage(event.target.files?.[0])}
            />
          </Field>

          {imagePreview && (
            <Field label={choose('图片预览', 'Voorbeeld')} htmlFor="pa-image-preview">
              <img
                id="pa-image-preview"
                src={imagePreview}
                alt=""
                className="product-image-preview"
              />
            </Field>
          )}

          <Field
            label={`${choose('价格 (€)', 'Prijs (€)')}`}
            htmlFor="pa-price"
            hint={choose(
              '可选：保存后写入每家门店的价目表。',
              'Optioneel: wordt in het prijzenboek van elke vestiging opgenomen.',
            )}
          >
            <input id="pa-price" name="price" type="number" min="0" step="0.01" />
          </Field>

          <MutationMessage error={error} success={success} />
          <div className="form-actions">
            <SubmitButton pending={pending || uploadingImage}>
              {choose('保存商品', 'Product opslaan')}
            </SubmitButton>
          </div>
        </form>
      </article>
    </section>
  );
}
