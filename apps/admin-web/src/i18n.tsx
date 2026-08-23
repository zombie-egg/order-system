import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';

export type AdminLanguage = 'zh-CN' | 'nl-NL';

const translations = {
  'zh-CN': {
    zh: '中文', nl: 'NL', language: '语言', refresh: '刷新', retry: '重试', close: '关闭', cancel: '取消', save: '保存', loading: '正在加载…', saving: '正在保存…',
    enabled: '已启用', disabled: '已停用', yes: '是', no: '否', view: '查看', hide: '收起',
    api: 'API 地址', tenantCode: '租户代码', username: '用户名', password: '密码', store: '门店', name: '名称', locale: '语言区域', codeSku: '代码 / SKU', sortOrder: '排序', version: '版本',
    dashboard: '经营概览', stores: '门店', users: '员工', catalog: '商品与定价', orders: '订单', refunds: '退款', reviews: '人工审核', reports: '报表', audit: '审计记录',
    signIn: '员工登录', signOut: '退出登录', admin: '管理后台', operations: '门店运营平台', skip: '跳至主要内容',
    category: '分类', optionGroup: '规格组', product: '商品', priceBook: '价目表', taxPolicy: '税务规则', promotion: '促销',
    create: '创建', update: '更新', selectStore: '请选择门店', assignedStore: '已分配门店',
    status: '状态', action: '操作', actions: '操作', order: '订单', payment: '支付', amount: '金额', total: '总计', date: '日期', time: '时间', detail: '详情',
  },
  'nl-NL': {
    zh: '中文', nl: 'NL', language: 'Taal', refresh: 'Vernieuwen', retry: 'Opnieuw proberen', close: 'Sluiten', cancel: 'Annuleren', save: 'Opslaan', loading: 'Laden…', saving: 'Opslaan…',
    enabled: 'Ingeschakeld', disabled: 'Uitgeschakeld', yes: 'Ja', no: 'Nee', view: 'Bekijken', hide: 'Verbergen',
    api: 'API-adres', tenantCode: 'Tenantcode', username: 'Gebruikersnaam', password: 'Wachtwoord', store: 'Vestiging', name: 'Naam', locale: 'Taalregio', codeSku: 'Code / SKU', sortOrder: 'Sorteervolgorde', version: 'Versie',
    dashboard: 'Operationeel overzicht', stores: 'Vestigingen', users: 'Medewerkers', catalog: 'Assortiment en prijzen', orders: 'Bestellingen', refunds: 'Terugbetalingen', reviews: 'Handmatige beoordeling', reports: 'Rapporten', audit: 'Auditlog',
    signIn: 'Medewerkerslogin', signOut: 'Uitloggen', admin: 'Beheeromgeving', operations: 'Vestigingsbeheer', skip: 'Naar hoofdinhoud',
    category: 'Categorie', optionGroup: 'Optiegroep', product: 'Product', priceBook: 'Prijzenboek', taxPolicy: 'Belastingbeleid', promotion: 'Promotie',
    create: 'Aanmaken', update: 'Bijwerken', selectStore: 'Kies een vestiging', assignedStore: 'Toegewezen vestiging',
    status: 'Status', action: 'Actie', actions: 'Acties', order: 'Bestelling', payment: 'Betaling', amount: 'Bedrag', total: 'Totaal', date: 'Datum', time: 'Tijd', detail: 'Details',
  },
} as const;

type TranslationKey = keyof (typeof translations)['zh-CN'];
interface I18nValue {
  language: AdminLanguage;
  setLanguage: (language: AdminLanguage) => void;
  t: (key: TranslationKey) => string;
  choose: (chinese: string, dutch: string) => string;
}

const I18nContext = createContext<I18nValue | null>(null);
const LANGUAGE_KEY = 'sippilot-admin-language';

export function AdminI18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<AdminLanguage>(() =>
    localStorage.getItem(LANGUAGE_KEY) === 'nl-NL' ? 'nl-NL' : 'zh-CN',
  );
  useEffect(() => {
    localStorage.setItem(LANGUAGE_KEY, language);
    document.documentElement.lang = language;
  }, [language]);
  const value = useMemo<I18nValue>(() => ({
    language,
    setLanguage,
    t: (key) => translations[language][key],
    choose: (chinese, dutch) => (language === 'zh-CN' ? chinese : dutch),
  }), [language]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useAdminI18n(): I18nValue {
  const context = useContext(I18nContext);
  if (!context) throw new Error('useAdminI18n must be used inside AdminI18nProvider');
  return context;
}

export function LanguageSwitch() {
  const { language, setLanguage, t } = useAdminI18n();
  return <div className="admin-language-switch" aria-label={t('language')}>
    <button type="button" className={language === 'zh-CN' ? 'active' : ''} onClick={() => setLanguage('zh-CN')}>{t('zh')}</button>
    <button type="button" className={language === 'nl-NL' ? 'active' : ''} onClick={() => setLanguage('nl-NL')}>{t('nl')}</button>
  </div>;
}
