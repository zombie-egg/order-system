import { useEffect, useState } from 'react';
import type { ApiClient } from '../api';
import { Field, LoadingState, MutationMessage, PageHeader, SubmitButton } from '../components';
import { resizeImageToDataUrl } from '../format';
import { useAdminI18n } from '../i18n';
import type { Branding } from '../types';

interface Props {
  api: ApiClient;
  canWrite: boolean;
}

export function BrandingPage({ api, canWrite }: Props) {
  const { choose } = useAdminI18n();
  const [branding, setBranding] = useState<Branding | null>(null);
  const [merchantName, setMerchantName] = useState('');
  const [logoUrl, setLogoUrl] = useState<string | null>(null);
  const [logoPreview, setLogoPreview] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    void api.get<Branding>('/admin/organization/branding').then((data) => {
      setBranding(data);
      setMerchantName(data.merchant_name);
      setLogoUrl(data.logo_url);
      setLogoPreview(data.logo_url);
    }, setError);
  }, [api]);

  const handleLogo = async (file: File | undefined) => {
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const dataUrl = await resizeImageToDataUrl(file, 512, 0.85);
      setLogoPreview(dataUrl);
      const result = await api.post<{ image_url: string }>('/admin/catalog/product-images', {
        image_data: dataUrl,
      });
      setLogoUrl(result.image_url);
    } catch (cause) {
      setError(cause);
    } finally {
      setUploading(false);
    }
  };

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canWrite) return;
    setPending(true);
    setError(null);
    setSuccess(null);
    try {
      await api.request('/admin/organization/branding', {
        method: 'PUT',
        body: {
          merchant_name: merchantName.trim() || null,
          logo_url: logoUrl,
        },
      });
      setSuccess(
        choose('品牌信息已保存。顾客点餐界面顶部会立即显示商户名称、logo 和分店名。', 'Merkinfo opgeslagen. De kiosk toont nu meteen de naam, het logo en de vestiging.'),
      );
    } catch (cause) {
      setError(cause);
    } finally {
      setPending(false);
    }
  };

  if (!branding && !error) {
    return <LoadingState label={choose('正在加载品牌信息…', 'Merkinfo laden…')} />;
  }

  return (
    <section>
      <PageHeader
        title={choose('品牌设置', 'Merkinstellingen')}
        description={choose(
          '设置显示在顾客点餐界面左上角的商家名称、Logo 和分店名称。分店名称可在「门店」中单独编辑。',
          'Beheer de merknaam en het logo die linksboven in de kiosk worden getoond. Vestigingsnamen beheer je in “Vestigingen”.',
        )}
      />
      <form className="card form-grid" onSubmit={(event) => void save(event)}>
        <Field label={`${choose('商户名称', 'Merknaam')} *`} htmlFor="brand-name">
          <input
            id="brand-name"
            required
            value={merchantName}
            onChange={(e) => setMerchantName(e.target.value)}
            placeholder={choose('例如：Milk Tea House', 'Bijv. Milk Tea House')}
          />
        </Field>
        <Field
          label={choose('商户 Logo', 'Merklogo')}
          htmlFor="brand-logo"
          hint={choose('JPG/PNG/WebP，保存后会显示在点餐界面。', 'JPG/PNG/WebP, wordt op de kiosk getoond.')}
        >
          <input
            id="brand-logo"
            type="file"
            accept="image/*"
            disabled={uploading}
            onChange={(event) => void handleLogo(event.target.files?.[0])}
          />
        </Field>
        {logoPreview && (
          <Field label={choose('Logo 预览', 'Logo voorbeeld')} htmlFor="brand-logo-preview">
            <img id="brand-logo-preview" src={logoPreview} alt="" className="product-image-preview" />
          </Field>
        )}
        <MutationMessage error={error} success={success} />
        <div className="form-actions">
          <SubmitButton pending={pending || uploading}>{choose('保存品牌信息', 'Merkinfo opslaan')}</SubmitButton>
        </div>
      </form>
    </section>
  );
}
