import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import type { ApiClient } from '../api';
import {
  EmptyState,
  ErrorState,
  Field,
  LoadingState,
  MutationMessage,
  PageHeader,
  StatusBadge,
  SubmitButton,
} from '../components';
import { formChecked, formNumber } from '../form';
import { useAsyncResource } from '../hooks';
import type { CreatedStore, KdsBoard, StoreConnection, StoreDeviceCredentials, StorePolicy, StoreWithPolicy } from '../types';
import { useAdminI18n } from '../i18n';

export function StoresPage({
  api,
  canWrite,
  canAddStore,
}: {
  api: ApiClient;
  canWrite: boolean;
  canAddStore: boolean;
}) {
  const { choose } = useAdminI18n();
  const loader = useCallback(() => api.get<StoreWithPolicy[]>('/admin/organization/stores'), [api]);
  const resource = useAsyncResource(loader);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [adding, setAdding] = useState(false);
  const [editingStore, setEditingStore] = useState(false);
  const [editName, setEditName] = useState('');
  const [editCity, setEditCity] = useState('');
  const [deviceCreds, setDeviceCreds] = useState<StoreDeviceCredentials | null>(null);
  const [deviceMessage, setDeviceMessage] = useState<string | null>(null);
  const [deviceBusy, setDeviceBusy] = useState(false);
  const [deviceError, setDeviceError] = useState<unknown>(null);
  const [copiedField, setCopiedField] = useState<string | null>(null);
  const [kdsBoard, setKdsBoard] = useState<KdsBoard | null>(null);
  const [kdsLoading, setKdsLoading] = useState(false);
  const [kdsSaving, setKdsSaving] = useState(false);
  const [connection, setConnection] = useState<StoreConnection | null>(null);
  const [connectionLoading, setConnectionLoading] = useState(false);
  const [createdKit, setCreatedKit] = useState<{
    tenantCode: string;
    store: { name: string; code: string; city: string | null };
    managerUsername: string;
    managerDisplayName: string;
    managerPassword: string;
    deviceCredentials: StoreDeviceCredentials;
  } | null>(null);

  const openDeviceCredentials = (creds: StoreDeviceCredentials, message: string | null) => {
    setDeviceCreds(creds);
    setDeviceMessage(message);
    setDeviceError(null);
    setCopiedField(null);
  };

  const resetDeviceCredentials = () => {
    if (!selected) return;
    setDeviceBusy(true);
    setDeviceError(null);
    void api
      .post<StoreDeviceCredentials>(
        `/admin/organization/stores/${selected.store.id}/device-credentials/reset`,
      )
      .then(
        (creds) => {
          openDeviceCredentials(
            creds,
            choose('设备凭据已重新生成，请妥善保存。', 'Apparaatgegevens zijn opnieuw gegenereerd. Bewaar ze goed.'),
          );
        },
        (error: unknown) => setDeviceError(error),
      )
      .finally(() => setDeviceBusy(false));
  };

  const copyValue = (label: string, value: string) => {
    if (navigator.clipboard?.writeText) {
      void navigator.clipboard.writeText(value).then(() => {
        setCopiedField(label);
        window.setTimeout(() => setCopiedField(null), 1600);
      });
    }
  };

  useEffect(() => {
    if (!selectedId) {
      setKdsBoard(null);
      return;
    }
    let active = true;
    setKdsLoading(true);
    api
      .get<KdsBoard>(`/admin/organization/stores/${selectedId}/kds-board`)
      .then(
        (board) => {
          if (active) setKdsBoard(board);
        },
        () => {
          if (active) setKdsBoard(null);
        },
      )
      .finally(() => {
        if (active) setKdsLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setConnection(null);
      return;
    }
    let active = true;
    setConnectionLoading(true);
    api
      .get<StoreConnection>(`/admin/organization/stores/${selectedId}/connection`)
      .then(
        (conn) => {
          if (active) setConnection(conn);
        },
        () => {
          if (active) setConnection(null);
        },
      )
      .finally(() => {
        if (active) setConnectionLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, selectedId]);

  const saveKdsBoard = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected || !kdsBoard) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const rawName = data.get('board_name');
    const rawTitle = data.get('board_title');
    const name = (typeof rawName === 'string' ? rawName : '').trim();
    const displayTitle = (typeof rawTitle === 'string' ? rawTitle : '').trim();
    const enabled = formChecked(form, 'board_enabled');
    setKdsSaving(true);
    setMutationError(null);
    setSuccess(null);
    void api
      .patch<KdsBoard>(`/admin/organization/stores/${selected.store.id}/kds-board`, {
        name: name || undefined,
        display_title: displayTitle || undefined,
        enabled,
        expected_version: kdsBoard.version,
      })
      .then(
        (board) => {
          setKdsBoard(board);
          setSuccess(choose('看板配置已保存。', 'Bordinformatie opgeslagen.'));
        },
        (error: unknown) => setMutationError(error),
      )
      .finally(() => setKdsSaving(false));
  };

  useEffect(() => {
    if (!selectedId && resource.data?.[0]) {
      setSelectedId(resource.data[0].store.id);
    }
  }, [resource.data, selectedId]);

  const selected = resource.data?.find((entry) => entry.store.id === selectedId) ?? null;
  const visibleStores = useMemo(() => resource.data?.filter(({ store, policy }) => `${store.name} ${store.code} ${store.city ?? ''} ${policy.accepting_orders ? 'open' : 'closed'}`.toLowerCase().includes(search.trim().toLowerCase())) ?? [], [resource.data, search]);
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    setPending(true);
    setMutationError(null);
    setSuccess(null);
    const form = event.currentTarget;
    void api
      .patch<StorePolicy>(`/admin/organization/stores/${selected.store.id}/policy`, {
        accepting_orders: formChecked(form, 'accepting_orders'),
        max_open_tickets: formNumber(form, 'max_open_tickets'),
        kds_heartbeat_seconds: formNumber(form, 'kds_heartbeat_seconds'),
        printer_fallback_enabled: formChecked(form, 'printer_fallback_enabled'),
        takeaway_fee_enabled: formChecked(form, 'takeaway_fee_enabled'),
        takeaway_fee_minor: Math.round(formNumber(form, 'takeaway_fee_eur') * 100),
        expected_version: selected.policy.version,
      })
      .then(
        (policy) => {
          resource.setData(
            (current) =>
              current?.map((entry) =>
                entry.store.id === selected.store.id ? { ...entry, policy } : entry,
              ) ?? null,
          );
          setPending(false);
          setSuccess(choose('门店策略已更新。', 'Vestigingsbeleid is bijgewerkt.'));
        },
        (error: unknown) => {
          setPending(false);
          setMutationError(error);
        },
      );
  };

  const saveStore = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    setPending(true);
    setMutationError(null);
    setSuccess(null);
    const form = event.currentTarget;
    const data = new FormData(form);
    const rawName = data.get('name');
    const rawCity = data.get('city');
    const name = typeof rawName === 'string' ? rawName.trim() : '';
    const city = (typeof rawCity === 'string' ? rawCity.trim() : '') || null;
    void api
      .request(`/admin/organization/stores/${selected.store.id}`, {
        method: 'PATCH',
        body: { name: name || undefined, city: city ?? undefined, expected_version: selected.store.version },
      })
      .then(
        () => {
          setPending(false);
          setEditingStore(false);
          setSuccess(choose('门店信息已更新。', 'Vestigingsgegevens bijgewerkt.'));
          void resource.reload();
        },
        (error: unknown) => {
          setPending(false);
          setMutationError(error);
        },
      );
  };

  const openEdit = () => {
    if (!selected) return;
    setEditName(selected.store.name);
    setEditCity(selected.store.city ?? '');
    setEditingStore(true);
  };

  return (
    <section>
      <PageHeader
        title={choose('门店与营业策略', 'Vestigingen en bedrijfsbeleid')}
        description={choose('查看已分配门店，并控制点餐机是否可接收订单。', 'Bekijk toegewezen vestigingen en bepaal of kiosken bestellingen mogen aannemen.')}
      />
      <div className="page-actions">{canAddStore ? <button type="button" className="primary-button" onClick={() => setAdding(true)} disabled={!canWrite}>{choose('添加门店', 'Vestiging toevoegen')}</button> : null}</div>
      <Field label={choose('搜索门店', 'Vestiging zoeken')} htmlFor="store-search"><input id="store-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder={choose('名称、代码、城市或营业状态', 'Naam, code, plaats of status')} />{search && <button type="button" className="link-button" onClick={() => setSearch('')}>{choose('清空搜索', 'Wissen')}</button>}</Field>
      {resource.loading ? <LoadingState label={choose('正在加载门店…', 'Vestigingen laden…')} /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState title={choose('暂无门店', 'Geen vestigingen')} detail={choose('当前账号未分配任何启用的门店。', 'Aan dit account is geen actieve vestiging toegewezen.')} />
      ) : null}
      {resource.data && resource.data.length > 0 ? (
        <div className="split-layout">
          <aside className="selection-list" aria-label={choose('已分配门店', 'Toegewezen vestigingen')}>
            {visibleStores.map((entry) => (
              <button
                type="button"
                key={entry.store.id}
                className={entry.store.id === selectedId ? 'selected' : ''}
                onClick={() => setSelectedId(entry.store.id)}
              >
                <strong>{entry.store.name}</strong>
                <span>{entry.store.code}</span>
                <StatusBadge value={entry.policy.accepting_orders} />
              </button>
            ))}
            {visibleStores.length === 0 && <EmptyState title={choose('没有匹配的门店', 'Geen vestigingen gevonden')} detail={choose('请尝试其他关键词或清空搜索。', 'Probeer een andere zoekterm of wis de zoekopdracht.')} />}
          </aside>
          {selected ? (
            <article className="card">
              <header className="card-header">
                <div>
                  <h2>{selected.store.name}</h2>
                  <p>
                    {selected.store.country_code} · {selected.store.currency} ·{' '}
                    {selected.store.locale}
                  </p>
                </div>
                <StatusBadge value={selected.store.active} />
              </header>
              <dl className="definition-grid">
                <div>
                  <dt>{choose('城市', 'Plaats')}</dt>
                  <dd>{selected.store.city ?? '—'}</dd>
                </div><div>
                  <dt>{choose('时区', 'Tijdzone')}</dt>
                  <dd>{selected.store.timezone}</dd>
                </div>
                <div>
                  <dt>{choose('策略版本', 'Beleidsversie')}</dt>
                  <dd>{selected.policy.version}</dd>
                </div>
              </dl>
              <section className="kds-board-section connection-section">
                <header className="card-header">
                  <div>
                    <h3>{choose('连接信息', 'Verbindinggegevens')}</h3>
                    <p>{choose('租户、店长账号与该店的 Kiosk / KDS 设备。', 'Tenant, manageraccount en de kiosk-/KDS-apparaten van deze vestiging.')}</p>
                  </div>
                </header>
                {connectionLoading ? (
                  <LoadingState label={choose('正在加载连接信息…', 'Verbindinggegevens laden…')} />
                ) : connection ? (
                  <>
                    <dl className="compact-list connection-list">
                      <div>
                        <dt>{choose('租户代码', 'Tenantcode')}</dt>
                        <dd>{connection.tenant_code || '—'}</dd>
                      </div>
                      <div>
                        <dt>{choose('Kiosk ID', 'Kiosk-ID')}</dt>
                        <dd className="monospace">{connection.kiosk_id ?? '—'}</dd>
                      </div>
                      <div>
                        <dt>{choose('KDS 工位 ID', 'KDS-station-ID')}</dt>
                        <dd className="monospace">{connection.endpoint_id ?? '—'}</dd>
                      </div>
                    </dl>
                    <div className="manager-list">
                    <strong>{choose('店长账号', 'Manageraccount')}</strong>
                    {connection.managers.length > 0 ? (
                      connection.managers.map((manager) => (
                        <p key={manager.user_id} className="manager-row">
                          <span>{manager.display_name}</span>
                          <code>{manager.username}</code>
                          {!manager.active ? <StatusBadge value="DISABLED" /> : null}
                        </p>
                      ))
                    ) : (
                      <p className="muted">{choose('尚未配置店长账号。', 'Nog geen manageraccount ingesteld.')}</p>
                    )}
                    </div>
                  </>
                ) : (
                  <p className="muted">{choose('暂无连接信息。', 'Geen verbindinggegevens.')}</p>
                )}
              </section>
              {editingStore ? (
                <form className="form-grid" onSubmit={saveStore}>
                  <Field label={`${choose('门店名称', 'Naam')} *`} htmlFor="edit-store-name">
                    <input id="edit-store-name" name="name" required defaultValue={editName} autoFocus />
                  </Field>
                  <Field label={choose('城市/地址', 'Plaats/adres')} htmlFor="edit-store-city">
                    <input id="edit-store-city" name="city" defaultValue={editCity} />
                  </Field>
                  <MutationMessage error={mutationError} success={null} />
                  <div className="form-actions">
                    <button type="button" className="button button-secondary" onClick={() => setEditingStore(false)}>
                      {choose('取消', 'Annuleren')}
                    </button>
                    <SubmitButton pending={pending}>{choose('保存', 'Opslaan')}</SubmitButton>
                  </div>
                </form>
              ) : (
                <div className="button-row">
                  <button type="button" className="button button-secondary" onClick={openEdit} disabled={!canWrite}>
                    {choose('编辑门店信息', 'Vestiging bewerken')}
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={resetDeviceCredentials}
                    disabled={!canWrite || deviceBusy}
                  >
                    {deviceBusy
                      ? '…'
                      : choose('重置设备凭据', 'Apparaatgegevens resetten')}
                  </button>
                </div>
              )}
              <MutationMessage error={mutationError} success={success} />
              <form
                key={`${selected.store.id}-${selected.policy.version}`}
                className="form-grid"
                onSubmit={submit}
              >
                <label className="check-field">
                  <input
                    type="checkbox"
                    name="accepting_orders"
                    defaultChecked={selected.policy.accepting_orders}
                    disabled={!canWrite}
                  />{' '}
                  {choose('接受订单', 'Bestellingen accepteren')}
                </label>
                <Field label={choose('最大待制作单数', 'Maximum aantal open tickets')} htmlFor="max_open_tickets">
                  <input
                    id="max_open_tickets"
                    name="max_open_tickets"
                    type="number"
                    min="1"
                    max="1000"
                    defaultValue={selected.policy.max_open_tickets}
                    disabled={!canWrite}
                    required
                  />
                </Field>
                <Field label={choose('KDS 心跳间隔（秒）', 'KDS-heartbeat (seconden)')} htmlFor="kds_heartbeat_seconds">
                  <input
                    id="kds_heartbeat_seconds"
                    name="kds_heartbeat_seconds"
                    type="number"
                    min="5"
                    max="300"
                    defaultValue={selected.policy.kds_heartbeat_seconds}
                    disabled={!canWrite}
                    required
                  />
                </Field>
                <label className="check-field">
                  <input
                    type="checkbox"
                    name="takeaway_fee_enabled"
                    defaultChecked={selected.policy.takeaway_fee_enabled}
                    disabled={!canWrite}
                  />{' '}
                  {choose('打包收取包装费', 'Verpakkingskosten voor meenemen')}
                </label>
                <Field label={choose('每笔包装费（EUR）', 'Verpakkingskosten per bestelling (EUR)')} htmlFor="takeaway_fee_eur">
                  <input
                    id="takeaway_fee_eur"
                    name="takeaway_fee_eur"
                    type="number"
                    min="0"
                    max="1000000"
                    step="0.01"
                    defaultValue={(selected.policy.takeaway_fee_minor / 100).toFixed(2)}
                    disabled={!canWrite}
                    required
                  />
                </Field>
                <label className="check-field">
                  <input
                    type="checkbox"
                    name="printer_fallback_enabled"
                    defaultChecked={selected.policy.printer_fallback_enabled}
                    disabled={!canWrite}
                  />{' '}
                  {choose('启用打印机备用方案', 'Printerreserve inschakelen')}
                </label>
                {canWrite ? (
                  <SubmitButton pending={pending}>{choose('保存策略', 'Beleid opslaan')}</SubmitButton>
                ) : (
                  <p className="muted">{choose('只读：需要 organization:write 权限。', 'Alleen lezen: de machtiging organization:write is vereist.')}</p>
                )}
              </form>
              <section className="kds-board-section">
                <header className="card-header">
                  <div>
                    <h3>{choose('厨房看板配置', 'Keukendisplay configuratie')}</h3>
                    <p>{choose('设置该店厨房看板(KDS)的显示信息。', 'Stel de weergave van de keukendisplay (KDS) van deze vestiging in.')}</p>
                  </div>
                </header>
                {kdsLoading ? (
                  <LoadingState label={choose('正在加载看板配置…', 'Bordinformatie laden…')} />
                ) : kdsBoard ? (
                  <form className="form-grid" onSubmit={saveKdsBoard}>
                    <Field label={choose('看板名称', 'Naam bord')} htmlFor="kds-name">
                      <input id="kds-name" name="board_name" defaultValue={kdsBoard.name} maxLength={120} disabled={!canWrite} required />
                    </Field>
                    <Field label={choose('看板显示标题', 'Titel op het bord')} htmlFor="kds-title">
                      <input id="kds-title" name="board_title" defaultValue={kdsBoard.display_title ?? ''} maxLength={120} placeholder={choose('例如：主吧台', 'Bijv. Hoofdbar')} disabled={!canWrite} />
                    </Field>
                    <label className="check-field">
                      <input type="checkbox" name="board_enabled" defaultChecked={kdsBoard.enabled} disabled={!canWrite} />{' '}
                      {choose('启用看板', 'Bord inschakelen')}
                    </label>
                    {canWrite ? (
                      <SubmitButton pending={kdsSaving}>{choose('保存看板配置', 'Bordinformatie opslaan')}</SubmitButton>
                    ) : (
                      <p className="muted">{choose('只读：需要 organization:write 权限。', 'Alleen lezen: de machtiging organization:write is vereist.')}</p>
                    )}
                  </form>
                ) : (
                  <p className="muted standalone-message">{choose('该店尚未初始化厨房看板，请先在「重置设备凭据」后重试。', 'Deze vestiging heeft nog geen keukendisplay. Reset eerst de apparaatgegevens en probeer opnieuw.')}</p>
                )}
              </section>
            </article>
          ) : null}
        </div>
      ) : null}
      {adding && (
        <div className="dialog-backdrop">
          <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="add-store-title">
            <h2 id="add-store-title">{choose('添加门店', 'Vestiging toevoegen')}</h2>
            <form
              className="form-grid"
              onSubmit={(event) => {
                event.preventDefault();
                const form = event.currentTarget;
                const data = new FormData(form);
                const rawName = data.get('name');
                const rawCity = data.get('city');
                const rawMgrName = data.get('manager_display_name');
                const rawMgrUser = data.get('manager_username');
                const rawMgrPass = data.get('manager_password');
                const name = (typeof rawName === 'string' ? rawName : '').trim();
                const city = (typeof rawCity === 'string' ? rawCity : '').trim() || null;
                const managerDisplayName = (typeof rawMgrName === 'string' ? rawMgrName : '').trim();
                const managerUsername = (typeof rawMgrUser === 'string' ? rawMgrUser : '').trim();
                const managerPassword = (typeof rawMgrPass === 'string' ? rawMgrPass : '').trim();
                setPending(true);
                setMutationError(null);
                void api
                  .post<CreatedStore>('/admin/organization/stores', {
                    name,
                    city,
                    manager_display_name: managerDisplayName,
                    manager_username: managerUsername,
                    manager_password: managerPassword,
                  })
                  .then((created) => {
                    resource.setData((current) => [...(current ?? []), created]);
                    setSelectedId(created.store.id);
                    setAdding(false);
                    if (created.device_credentials) {
                      setCreatedKit({
                        tenantCode: created.tenant_code,
                        store: {
                          name: created.store.name,
                          code: created.store.code,
                          city: created.store.city ?? null,
                        },
                        managerUsername: created.manager_account.username,
                        managerDisplayName: created.manager_account.display_name,
                        managerPassword,
                        deviceCredentials: created.device_credentials,
                      });
                    } else {
                      setSuccess(choose('门店已创建。', 'Vestiging aangemaakt.'));
                    }
                  }, (error: unknown) => setMutationError(error))
                  .finally(() => setPending(false));
              }}
            >
              <Field label={choose('门店名称', 'Naam')} htmlFor="new-store-name">
                <input id="new-store-name" name="name" required autoFocus />
              </Field>
              <Field label={choose('城市/地址', 'Plaats/adres')} htmlFor="new-store-city">
                <input id="new-store-city" name="city" />
              </Field>
              <div className="form-grid-dialog-subhead">{choose('门店店长账号', 'Vestigingsmanager')}</div>
              <Field label={`${choose('店长姓名', 'Naam manager')} *`} htmlFor="new-mgr-name">
                <input id="new-mgr-name" name="manager_display_name" required maxLength={160} />
              </Field>
              <Field label={`${choose('店长用户名', 'Gebruikersnaam manager')} *`} htmlFor="new-mgr-user" hint={choose('用于登录后台与连接厨房看板(KDS)。', 'Voor login en het koppelen van de keukendisplay (KDS).')}>
                <input id="new-mgr-user" name="manager_username" required maxLength={120} autoComplete="off" />
              </Field>
              <Field label={`${choose('店长初始密码', 'Initieel wachtwoord manager')} *`} htmlFor="new-mgr-pass" hint={choose('至少 12 位，仅创建时显示一次。', 'Minimaal 12 tekens, slechts één keer getoond.')}>
                <input id="new-mgr-pass" name="manager_password" type="password" required minLength={12} autoComplete="new-password" />
              </Field>
              <p className="muted">NL · EUR · nl-NL · Europe/Amsterdam</p>
              <div className="dialog-actions">
                <button type="button" className="secondary-button" onClick={() => setAdding(false)}>{choose('取消', 'Annuleren')}</button>
                <SubmitButton pending={pending}>{choose('创建门店', 'Vestiging maken')}</SubmitButton>
              </div>
            </form>
          </section>
        </div>
      )}
      {createdKit ? (
        <ConnectKitDialog
          kit={createdKit}
          copiedField={copiedField}
          onCopy={(label, value) => copyValue(label, value)}
          onClose={() => setCreatedKit(null)}
        />
      ) : null}
      {deviceCreds ? <DeviceCredentialsDialog creds={deviceCreds} message={deviceMessage} error={deviceError} copiedField={copiedField} onCopy={(label, value) => copyValue(label, value)} onClose={() => setDeviceCreds(null)} /> : null}
    </section>
  );
}

function DeviceCredentialsDialog({
  creds,
  message,
  error,
  copiedField,
  onCopy,
  onClose,
}: {
  creds: StoreDeviceCredentials;
  message: string | null;
  error: unknown;
  copiedField: string | null;
  onCopy: (label: string, value: string) => void;
  onClose: () => void;
}) {
  const { t, choose } = useAdminI18n();
  const rows = [
    { label: t('kioskId'), value: creds.kiosk_id ?? '—', key: 'kiosk_id' },
    { label: t('kioskKey'), value: creds.kiosk_key ?? '—', key: 'kiosk_key', secret: !creds.kiosk_key },
    { label: t('stationId'), value: creds.station_id ?? '—', key: 'station_id' },
    { label: t('endpointId'), value: creds.endpoint_id ?? '—', key: 'endpoint_id' },
    { label: t('endpointKey'), value: creds.endpoint_key ?? '—', key: 'endpoint_key', secret: !creds.endpoint_key },
  ];
  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="device-cred-title">
        <h2 id="device-cred-title">{choose('设备凭据', 'Apparaatgegevens')}</h2>
        <p className="muted">{message ?? choose('按门店查看其 Kiosk / KDS 设备。', 'Bekijk de kiosk- en KDS-apparaten per vestiging.')}</p>
        {error ? <ErrorState error={error} /> : null}
        <div className="device-cred-list">
          {rows.map((row) => (
            <div className="device-cred-row" key={row.key}>
              <span className="device-cred-label">{row.label}</span>
              <code className="device-cred-value">{row.value}</code>
              {row.value !== '—' && (
                <button
                  type="button"
                  className="button button-secondary device-cred-copy"
                  onClick={() => onCopy(row.label, row.value)}
                >
                  {copiedField === row.label ? t('copied') : t('copy')}
                </button>
              )}
            </div>
          ))}
        </div>
        <p className="muted device-cred-warning">{choose('设备密钥仅显示一次，请妥善保存，切勿泄露。', 'Apparaatsleutels worden slechts één keer getoond. Bewaar ze zorgvuldig en deel ze niet.')}</p>
        <div className="dialog-actions">
          <button type="button" className="button button-secondary" onClick={onClose}>
            {t('closeDeviceDialog')}
          </button>
        </div>
      </section>
    </div>
  );
}

function ConnectKitDialog({
  kit,
  copiedField,
  onCopy,
  onClose,
}: {
  kit: {
    tenantCode: string;
    store: { name: string; code: string; city: string | null };
    managerUsername: string;
    managerDisplayName: string;
    managerPassword: string;
    deviceCredentials: StoreDeviceCredentials;
  };
  copiedField: string | null;
  onCopy: (label: string, value: string) => void;
  onClose: () => void;
}) {
  const { t, choose } = useAdminI18n();
  const groups = [
    {
      title: choose('厨房看板(KDS)连接', 'Keukendisplay (KDS) verbinding'),
      rows: [
        { label: t('endpointId'), value: kit.deviceCredentials.endpoint_id ?? '—', key: 'endpoint_id' },
        { label: t('endpointKey'), value: kit.deviceCredentials.endpoint_key ?? '—', key: 'endpoint_key' },
      ],
    },
    {
      title: choose('店长后台登录', 'Managerlogin beheeromgeving'),
      rows: [
        { label: choose('租户代码', 'Tenantcode'), value: kit.tenantCode, key: 'tenant_code' },
        { label: choose('店长用户名', 'Gebruikersnaam'), value: kit.managerUsername, key: 'mgr_user' },
        { label: choose('店长密码', 'Wachtwoord manager'), value: kit.managerPassword, key: 'mgr_pass' },
      ],
    },
    {
      title: choose('Kiosk 点单机设备', 'Kiosk-bestelling apparaat'),
      rows: [
        { label: t('kioskId'), value: kit.deviceCredentials.kiosk_id ?? '—', key: 'kiosk_id' },
        { label: t('kioskKey'), value: kit.deviceCredentials.kiosk_key ?? '—', key: 'kiosk_key' },
      ],
    },
  ];
  return (
    <div className="dialog-backdrop" role="presentation">
      <section className="dialog" role="dialog" aria-modal="true" aria-labelledby="connect-kit-title">
        <h2 id="connect-kit-title">{choose('门店连接信息', 'Verbindinggegevens vestiging')}</h2>
        <p className="muted">
          {choose(`门店：${kit.store.name} · ${kit.store.code}`, `Vestiging: ${kit.store.name} · ${kit.store.code}`)}
          {choose('。请把以下连接信息交给店长。', '. Geef deze verbindinggegevens aan de manager.')}
        </p>
        {groups.map((group) => (
          <div key={group.title}>
            <p className="connect-group-title">{group.title}</p>
            <div className="device-cred-list">
              {group.rows.map((row) => (
                <div className="device-cred-row" key={row.key}>
                  <span className="device-cred-label">{row.label}</span>
                  <code className="device-cred-value">{row.value}</code>
                  {row.value !== '—' && (
                    <button
                      type="button"
                      className="button button-secondary device-cred-copy"
                      onClick={() => onCopy(row.label, row.value)}
                    >
                      {copiedField === row.label ? t('copied') : t('copy')}
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
        <p className="muted device-cred-warning">{choose('密钥与密码仅显示一次，请妥善保存，切勿泄露。', 'Sleutels en wachtwoord worden slechts één keer getoond. Bewaar ze zorgvuldig en deel ze niet.')}</p>
        <div className="dialog-actions">
          <button type="button" className="button button-secondary" onClick={onClose}>
            {t('closeDeviceDialog')}
          </button>
        </div>
      </section>
    </div>
  );
}
