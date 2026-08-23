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
import { useAdminI18n } from '../i18n';

type FormKind = CatalogFormKind;

interface ProductImageUploadResponse {
  image_url: string;
}

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
  const { t, choose } = useAdminI18n();
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
  const [imageUrl, setImageUrl] = useState('');
  const [uploadingImage, setUploadingImage] = useState(false);

  const uploadImage = (file: File | null) => {
    if (!file) return;
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
      setError(new Error(choose('仅支持 JPG、PNG 或 WebP 图片。', 'Alleen JPG-, PNG- of WebP-afbeeldingen worden ondersteund.')));
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      setError(new Error(choose('图片大小不能超过 5MB。', 'De afbeelding mag niet groter zijn dan 5 MB.')));
      return;
    }
    const reader = new FileReader();
    setUploadingImage(true);
    setError(null);
    reader.onerror = () => {
      setUploadingImage(false);
      setError(new Error(choose('无法读取所选图片。', 'De geselecteerde afbeelding kan niet worden gelezen.')));
    };
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        setUploadingImage(false);
        setError(new Error(choose('无法读取所选图片。', 'De geselecteerde afbeelding kan niet worden gelezen.')));
        return;
      }
      void api.post<ProductImageUploadResponse>('/admin/catalog/product-images', {
        image_data: reader.result,
      }).then(
        ({ image_url }) => {
          setImageUrl(image_url);
          setUploadingImage(false);
        },
        (reason: unknown) => {
          setUploadingImage(false);
          setError(reason);
        },
      );
    };
    reader.readAsDataURL(file);
  };

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
          values: parseJsonArray(formText(form, 'items'), choose('规格选项', 'Optiewaarden')),
        };
      } else if (kind === 'product') {
        path = '/admin/catalog/products';
        payload = {
          store_id: storeId,
          category_id: formText(form, 'category_id'),
          sku: formText(form, 'code'),
          tax_category_code: formText(form, 'tax_category_code'),
          image_url: imageUrl || formText(form, 'image_url') || null,
          translations: {
            [formText(form, 'locale')]: {
              name: formText(form, 'name'),
              description: formText(form, 'description'),
            },
          },
          preparation_data: parseJsonObject(formText(form, 'preparation_data'), 'Preparation data'),
          allergen_data: parseJsonObject(formText(form, 'allergen_data'), 'Allergen data'),
          sort_order: formNumber(form, 'sort_order'),
          option_rules: parseJsonArray(formText(form, 'items'), choose('规格规则', 'Optieregels')),
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
          items: parseJsonArray(formText(form, 'items'), choose('价目表项目', 'Prijzenboekitems')),
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
          rates: parseJsonArray(formText(form, 'items'), choose('税率', 'Belastingtarieven')),
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
        setImageUrl('');
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
    { value: 'category', label: t('category'), enabled: canTenantWrite },
    { value: 'option-group', label: t('optionGroup'), enabled: canTenantWrite },
    { value: 'product', label: t('product'), enabled: canTenantWrite },
    { value: 'price-book', label: t('priceBook'), enabled: canStoreWrite },
    { value: 'tax-policy', label: t('taxPolicy'), enabled: canTenantWrite },
    { value: 'promotion', label: t('promotion'), enabled: canStoreWrite },
  ];
  const namedStoreIds = new Set(stores.map(({ store }) => store.id));
  const unnamedStoreIds = assignedStoreIds.filter((storeId) => !namedStoreIds.has(storeId));
  return (
    <section>
      <PageHeader
        title={t('catalog')}
        description={choose('创建分类、规格组、商品、价目表、税务规则和促销。', 'Maak categorieën, optiegroepen, producten, prijzenboeken, belastingbeleid en promoties.')}
      />
      <div className="tab-list" role="tablist" aria-label={choose('资源类型', 'Type gegevens')}> 
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
                setImageUrl('');
              }}
            >
              {option.label}
            </button>
          ))}
      </div>
      <MutationMessage error={error} success={success} />
      {!firstWritableKind ? (
        <div className="notice notice-info">
          {choose('此账号可查看商品，但没有修改商品或价格的权限。', 'Dit account kan het assortiment bekijken, maar mag geen assortiment of prijzen wijzigen.')}
        </div>
      ) : null}
      {firstWritableKind ? (
        <form key={kind} className="card form-grid" onSubmit={submit}>
          <Field label={t('store')} htmlFor="catalog_store">
            <select id="catalog_store" name="store_id" required defaultValue="">
              <option value="" disabled>
                {t('selectStore')}
              </option>
              {stores.map(({ store }) => (
                <option key={store.id} value={store.id}>
                  {store.name}
                </option>
              ))}
              {unnamedStoreIds.map((storeId) => (
                <option key={storeId} value={storeId}>
                  {t('assignedStore')} {storeId.slice(0, 8)}
                </option>
              ))}
            </select>
          </Field>
          {kind !== 'tax-policy' ? (
            <Field label={t('codeSku')} htmlFor="catalog_code">
              <input id="catalog_code" name="code" required />
            </Field>
          ) : null}
          {['category', 'option-group', 'product', 'promotion'].includes(kind) ? (
            <Field label={t('name')} htmlFor="catalog_name">
              <input id="catalog_name" name="name" required />
            </Field>
          ) : null}
          {['category', 'option-group', 'product'].includes(kind) ? (
            <>
              <Field label={t('locale')} htmlFor="catalog_locale">
                <input id="catalog_locale" name="locale" defaultValue="nl-NL" required />
              </Field>
              <Field label={t('sortOrder')} htmlFor="sort_order">
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
              <Field label={choose('分类 ID', 'Categorie-ID')} htmlFor="category_id">
                <input id="category_id" name="category_id" required />
              </Field>
              <Field label={choose('税务分类代码', 'Belastingcategoriecode')} htmlFor="tax_category_code">
                <input
                  id="tax_category_code"
                  name="tax_category_code"
                  defaultValue="STANDARD"
                  required
                />
              </Field>
              <Field label={choose('图片地址', 'Afbeeldings-URL')} htmlFor="image_url">
                <input
                  id="image_url"
                  name="image_url"
                  type="url"
                  value={imageUrl}
                  onChange={(event) => setImageUrl(event.target.value)}
                  placeholder="上传后会自动填入，也可粘贴图片链接"
                />
              </Field>
              <Field
                label={choose('上传商品图片', 'Productafbeelding uploaden')}
                htmlFor="product_image_file"
                hint={choose('支持 JPG、PNG、WebP，最大 5MB。建议使用约 2.2:1 的横图，点餐机将居中裁剪。', 'JPG, PNG en WebP tot 5 MB. Gebruik bij voorkeur een liggende afbeelding van circa 2,2:1; de kiosk snijdt deze gecentreerd bij.')}
              >
                <input
                  id="product_image_file"
                  type="file"
                  accept="image/jpeg,image/png,image/webp"
                  disabled={uploadingImage}
                  onChange={(event) => uploadImage(event.target.files?.[0] ?? null)}
                />
              </Field>
              {imageUrl ? (
                <figure className="catalog-image-preview">
                  <img src={imageUrl} alt={choose('商品图片预览', 'Voorvertoning productafbeelding')} />
                  <figcaption>{choose('商品卡片预览', 'Voorvertoning productkaart')}</figcaption>
                </figure>
              ) : null}
              <Field label={choose('描述', 'Beschrijving')} htmlFor="description">
                <textarea id="description" name="description" />
              </Field>
              <Field label={choose('制作信息 JSON', 'Bereidingsgegevens JSON')} htmlFor="preparation_data">
                <textarea id="preparation_data" name="preparation_data" defaultValue="{}" />
              </Field>
              <Field label={choose('过敏原 JSON', 'Allergenen JSON')} htmlFor="allergen_data">
                <textarea id="allergen_data" name="allergen_data" defaultValue="{}" />
              </Field>
            </>
          ) : null}
          {['price-book', 'tax-policy'].includes(kind) ? (
            <Field label={t('version')} htmlFor="catalog_version">
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
            <Field label={choose('货币', 'Valuta')} htmlFor="catalog_currency">
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
            <Field label={choose(kind === 'promotion' ? '开始时间' : '生效时间', kind === 'promotion' ? 'Start op' : 'Geldig vanaf')} htmlFor="valid_from">
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
              {choose(
                `后端会立即发布此资源，且有效期没有结束时间。如果门店已有已发布的${kind === 'price-book' ? '价目表' : '税务规则'}，在未来的替换接口能关闭当前有效期前，创建操作预计会被拒绝。`,
                `De backend publiceert dit direct met een onbegrensde geldigheid. Heeft de vestiging al een gepubliceerd ${kind === 'price-book' ? 'prijzenboek' : 'belastingbeleid'}, dan wordt aanmaken afgewezen totdat een toekomstige vervangingsfunctie de huidige periode kan sluiten.`,
              )}
            </div>
          ) : null}
          {kind === 'promotion' ? (
            <>
              <Field label={choose('促销类型', 'Promotietype')} htmlFor="promotion_type">
                <select id="promotion_type" name="promotion_type">
                  <option>PERCENTAGE</option>
                  <option>FIXED_AMOUNT</option>
                </select>
              </Field>
              <Field
                label={choose('优惠值', 'Waarde')}
                htmlFor="promotion_value"
                hint={choose('百分比促销填写百分数；固定金额促销填写欧元。', 'Vul een percentage in voor procentuele promoties en euro’s voor een vast bedrag.')}
              >
                <input id="promotion_value" name="value" inputMode="decimal" required />
              </Field>
              <Field label={choose('最低订单金额（欧元）', 'Minimaal bestelbedrag (EUR)')} htmlFor="minimum_total">
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
                  ? choose('规格选项 JSON', 'Optiewaarden JSON')
                  : kind === 'product'
                    ? '规格规则 JSON'
                    : kind === 'price-book'
                      ? choose('价格项目 JSON', 'Prijsitems JSON')
                      : choose('税率 JSON', 'Belastingtarieven JSON')
              }
              htmlFor="catalog_items"
              hint={
                kind === 'product'
                  ? choose('每一条规则绑定一个规格组；商品卡片点选后会严格按这里的必选、最多可选数量显示。', 'Elke regel koppelt een optiegroep; na selectie toont de productkaart precies de verplichte en maximale aantallen uit deze regel.')
                  : choose('必须是符合后端接口要求的 JSON 数组。', 'Dit moet een JSON-array zijn die aan de backendinterface voldoet。')
              }
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
                  choose('请确认门店没有重叠的已发布有效期，然后再次提交。', 'Bevestig dat de vestiging geen overlappende gepubliceerde periode heeft en dien daarna opnieuw in.'),
                )
              }
            >
              {choose('检查发布限制', 'Publicatiebeperking controleren')}
            </button>
          ) : (
            <SubmitButton pending={pending || uploadingImage}>
              {uploadingImage ? choose('正在上传图片…', 'Afbeelding uploaden…') : choose(`创建${kind === 'product' ? '商品' : ({ category: '分类', 'option-group': '规格组', 'price-book': '价目表', 'tax-policy': '税务规则', promotion: '促销' } as Record<string, string>)[kind]}`, `${({ category: 'Categorie', 'option-group': 'Optiegroep', product: 'Product', 'price-book': 'Prijzenboek', 'tax-policy': 'Belastingbeleid', promotion: 'Promotie' } as Record<string, string>)[kind]} aanmaken`)}
            </SubmitButton>
          )}
          {validityWarning ? (
            <SubmitButton pending={pending}>{choose('确认创建', 'Aanmaken bevestigen')}</SubmitButton>
          ) : null}
        </form>
      ) : null}
    </section>
  );
}
