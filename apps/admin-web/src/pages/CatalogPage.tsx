import { useMemo, useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
import { Field, MutationMessage, PageHeader, SubmitButton } from '../components';
import type { StoreWithPolicy } from '../types';
import { useAdminI18n } from '../i18n';

type Category = { id: string; name: string; storeId: string; active: boolean };

function formText(data: FormData, name: string): string {
  const value = data.get(name);
  return typeof value === 'string' ? value.trim() : '';
}

export function CatalogPage({ api, stores, canStoreWrite }: { api: ApiClient; stores: StoreWithPolicy[]; assignedStoreIds: string[]; canTenantWrite: boolean; canStoreWrite: boolean }) {
  const { choose } = useAdminI18n();
  const [storeId, setStoreId] = useState(stores[0]?.store.id ?? '');
  const [storeSearch, setStoreSearch] = useState('');
  const [productSearch, setProductSearch] = useState('');
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoryId, setCategoryId] = useState('');
  const [addingCategory, setAddingCategory] = useState(false);
  const [addingProduct, setAddingProduct] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const visibleStores = useMemo(() => stores.filter(({ store }) => `${store.name} ${store.code} ${store.city ?? ''}`.toLowerCase().includes(storeSearch.trim().toLowerCase())), [stores, storeSearch]);
  const submitCategory = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); const form = event.currentTarget; const name = formText(new FormData(form), 'name');
    if (!name || !storeId) return; setPending(true); setError(null);
    void api.post<{ id: string }>('/admin/catalog/categories', { store_id: storeId, code: name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || `category-${Date.now()}`, translations: { 'nl-NL': name }, sort_order: categories.length }).then(({ id }) => { setCategories((current) => [...current, { id, name, storeId, active: true }]); setCategoryId(id); setAddingCategory(false); setSuccess(choose('分类已创建，现在可以添加商品。', 'Categorie aangemaakt. Je kunt nu een product toevoegen.')); }, setError).finally(() => setPending(false));
  };
  const submitProduct = (event: FormEvent<HTMLFormElement>) => { event.preventDefault(); const form = event.currentTarget; const data = new FormData(form); const name = formText(data, 'name'); const price = Number(formText(data, 'price')); if (!name || !categoryId || !Number.isFinite(price) || price < 0) return; setPending(true); setError(null); void api.post<{ id: string }>('/admin/catalog/products', { store_id: storeId, category_id: categoryId, sku: `AUTO-${Date.now()}`, tax_category_code: 'VAT_STANDARD', translations: { 'nl-NL': { name, description: formText(data, 'description') } }, preparation_data: {}, allergen_data: {}, sort_order: 0, option_rules: [] }).then(() => { setAddingProduct(false); setSuccess(choose('商品已保存为可编辑草稿。', 'Product opgeslagen als concept.')); }, setError).finally(() => setPending(false)); };
  return <section>
    <PageHeader title={choose('商品管理', 'Productbeheer')} description={choose('选择门店，进入分类，再添加和发布商品。价格和定制项在商品编辑器中维护。', 'Kies een vestiging, open een categorie en voeg producten toe. Prijs en aanpassingen beheer je in de editor.')} />
    <div className="card form-grid"><Field label={choose('搜索门店', 'Vestiging zoeken')} htmlFor="catalog-store-search"><input id="catalog-store-search" value={storeSearch} onChange={(e) => setStoreSearch(e.target.value)} placeholder={choose('名称、代码或城市', 'Naam, code of plaats')} /></Field><Field label={choose('门店', 'Vestiging')} htmlFor="catalog-store"><select id="catalog-store" value={storeId} onChange={(e) => { setStoreId(e.target.value); setCategoryId(''); }}>{visibleStores.map(({ store }) => <option key={store.id} value={store.id}>{store.name} · {store.code}</option>)}</select></Field><MutationMessage error={null} success={success} /></div>
    {storeId && <><nav className="breadcrumb" aria-label={choose('位置', 'Locatie')}>{choose('商品管理', 'Productbeheer')} / {stores.find(({ store }) => store.id === storeId)?.store.name ?? ''}{categoryId ? ` / ${categories.find((c) => c.id === categoryId)?.name ?? ''}` : ''}</nav><div className="split-layout"><aside className="selection-list"><h2>{choose('分类', 'Categorieën')}</h2>{categories.filter((c) => c.storeId === storeId).map((category) => <button type="button" key={category.id} className={category.id === categoryId ? 'selected' : ''} aria-current={category.id === categoryId ? 'page' : undefined} onClick={() => setCategoryId(category.id)}>{category.name}</button>)}<button type="button" className="secondary-button" onClick={() => setAddingCategory(true)} disabled={!canStoreWrite}>＋ {choose('添加分类', 'Categorie toevoegen')}</button></aside><article className="card"><header className="card-header"><div><h2>{categoryId ? categories.find((c) => c.id === categoryId)?.name : choose('选择分类', 'Kies een categorie')}</h2><p>{categoryId ? choose('管理此分类中的商品。', 'Beheer producten in deze categorie.') : choose('还没有分类，添加第一个分类。', 'Nog geen categorie. Voeg de eerste toe.')}</p></div>{categoryId && <button type="button" className="primary-button" onClick={() => setAddingProduct(true)} disabled={!canStoreWrite}>＋ {choose('添加商品', 'Product toevoegen')}</button>}</header>{categoryId && <Field label={choose('搜索商品', 'Producten zoeken')} htmlFor="catalog-product-search"><input id="catalog-product-search" value={productSearch} onChange={(e) => setProductSearch(e.target.value)} placeholder={choose('商品名称或简介', 'Naam of beschrijving')} /></Field>} {!categoryId && <div className="empty-state"><strong>{choose('还没有分类', 'Nog geen categorieën')}</strong><p>{choose('添加第一个分类，开始建立菜单。', 'Voeg een categorie toe om je menu op te bouwen.')}</p></div>}</article></div></>}
    {(addingCategory || addingProduct) && <div className="dialog-backdrop" role="presentation"><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="catalog-dialog-title"><h2 id="catalog-dialog-title">{addingCategory ? choose('添加分类', 'Categorie toevoegen') : choose('添加商品', 'Product toevoegen')}</h2><form className="form-grid" onSubmit={addingCategory ? submitCategory : submitProduct}>{addingCategory ? <><Field label={choose('分类名称', 'Categorienaam')} htmlFor="category-name"><input id="category-name" name="name" required autoFocus /></Field></> : <><Field label={choose('商品名称', 'Productnaam')} htmlFor="product-name"><input id="product-name" name="name" required autoFocus /></Field><Field label={choose('简介', 'Beschrijving')} htmlFor="product-description"><textarea id="product-description" name="description" /></Field><Field label={choose('基础价格 (€)', 'Basisprijs (€)')} htmlFor="product-price"><input id="product-price" name="price" type="number" min="0" step="0.01" required /></Field></>}<MutationMessage error={error} success={null} /><div className="dialog-actions"><button type="button" className="secondary-button" onClick={() => { setAddingCategory(false); setAddingProduct(false); }}> {choose('取消', 'Annuleren')} </button><SubmitButton pending={pending}>{choose('保存', 'Opslaan')}</SubmitButton></div></form></section></div>}
  </section>;
}
