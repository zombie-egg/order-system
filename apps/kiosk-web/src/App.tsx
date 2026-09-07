import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ApiError,
  clearSessionKioskConfig,
  createConfiguredKioskApi,
  KioskApiClient,
  type KioskApi,
  type KioskRuntimeConfig,
} from './api';
import { DeviceSetup } from './DeviceSetup';
import {
  allergenNames,
  cartLineTotal,
  createIdempotencyKey,
  formatMoney,
  latestPaymentAttempt,
  paymentStatusLabel,
} from './format';
import { ProductCustomizer } from './ProductCustomizer';
import { ReceiptView } from './ReceiptView';
import {
  SterlingGateKineticNavigation,
  type KineticMenuItem,
} from './components/ui/sterling-gate-kinetic-navigation';
import type {
  CartLine,
  CatalogProduct,
  FulfillmentType,
  KioskStoreStatus,
  KioskOrder,
  KioskReceipt,
  PaymentMethod,
  Quote,
  StoreCatalog,
} from './types';

type CheckoutStep = 'browse' | 'review' | 'payment' | 'result';
type ConnectionState = 'checking' | 'online' | 'offline';

interface AppProps {
  api?: KioskApi | null;
}

interface UserFacingError {
  title: string;
  message: string;
  reference: string | null;
}

const terminalStatuses = new Set(['CLOSED', 'CANCELLED']);
const settledPaymentStatuses = new Set([
  'PAID',
  'REFUND_PENDING',
  'PARTIALLY_REFUNDED',
  'REFUNDED',
]);
const DEVICE_REFRESH_INTERVAL_MS = 30_000;
const DEVICE_OFFLINE_FAILURE_THRESHOLD = 2;
const CHECKOUT_SESSION_KEY = 'smart-drink:kiosk-checkout-session';
const CHECKOUT_SESSION_MAX_AGE_MS = 12 * 60 * 60 * 1000;
const kioskCopy = {
  'zh-CN': {
    steps: ['点餐', '确认', '支付', '完成'],
    brand: '开始点单',
    progress: '点单进度',
    checking: '正在连接', online: '已连接', offline: '无连接', changeKiosk: '更换设备',
    menu: '饮品菜单', assortment: '精选饮品', freshlyMade: '现点现做', choices: '种选择',
    explore: '探索菜单', add: '加入', customizable: '可定制 · 展开选择', cart: '购物车', order: '你的订单', emptyCart: '请选择饮品开始点单。',
    estimated: '预计总价', vat: '最终税费与优惠将在下一步计算。', review: '确认订单',
    loading: '正在加载菜单', wait: '请稍候…', unavailable: '菜单暂不可用', device: '修改设备信息',
    paused: '暂时无法点单', pausedDetail: '请联系店员，或稍后再试。', retry: '重新检查',
    checkOrder: '确认订单信息', edit: '修改', subtotal: '小计', discount: '优惠', tax: '税费', total: '合计',
    taxIncluded: '价格已含税。', taxAdded: '税费已加入总价。', paymentHow: '请选择支付方式',
    contactless: '非接触式支付', contactlessHint: '银行卡、手机或智能穿戴设备', card: '银行卡', cardHint: '请将卡插入支付终端',
    pay: '支付', processing: '请按支付终端上的提示操作，请勿关闭此页面。', refresh: '刷新状态',
    thankYou: '谢谢！', received: '已收到付款', pickup: '取餐号', preparing: '订单正在制作中。',
  },
  'nl-NL': {
    steps: ['Kiezen', 'Controleren', 'Betalen', 'Gereed'],
    brand: 'Bestel hier',
    progress: 'Voortgang van je bestelling',
    checking: 'Controleren', online: 'Verbonden', offline: 'Geen verbinding', changeKiosk: 'Kiosk wisselen',
    menu: 'Menu', assortment: 'Ons assortiment', freshlyMade: 'Vers bereid door ons team', choices: 'keuzes',
    explore: 'Ontdek menu', add: 'Toevoegen', customizable: 'Aanpasbaar · keuzes bekijken', cart: 'Winkelmand', order: 'Je bestelling', emptyCart: 'Kies een drankje om te beginnen.',
    estimated: 'Geschat totaal', vat: 'Definitieve BTW en kortingen worden hierna berekend.', review: 'Bestelling controleren',
    loading: 'Menu wordt geladen', wait: 'Even geduld…', unavailable: 'Menu niet beschikbaar', device: 'Apparaatgegevens wijzigen',
    paused: 'Nieuwe bestellingen zijn gepauzeerd', pausedDetail: 'Vraag een medewerker om hulp of probeer het later opnieuw.', retry: 'Opnieuw controleren',
    checkOrder: 'Klopt je bestelling?', edit: 'Wijzigen', subtotal: 'Subtotaal', discount: 'Korting', tax: 'BTW', total: 'Totaal',
    taxIncluded: 'Prijzen zijn inclusief BTW.', taxAdded: 'BTW is toegevoegd aan het totaal.', paymentHow: 'Hoe wil je betalen?',
    contactless: 'Contactloos', contactlessHint: 'Kaart, telefoon of wearable', card: 'Betaalkaart', cardHint: 'Steek de kaart in de terminal',
    pay: 'Betalen', processing: 'Volg de instructies op de betaalterminal. Sluit dit scherm niet.', refresh: 'Status vernieuwen',
    thankYou: 'Bedankt!', received: 'Betaling ontvangen', pickup: 'Afhaalnummer', preparing: 'Je bestelling wordt door ons team bereid.',
  },
} as const;

function checkoutStepsFor(locale: 'zh-CN' | 'nl-NL'): Array<{ id: CheckoutStep; label: string }> {
  return [
    { id: 'browse', label: kioskCopy[locale].steps[0] },
    { id: 'review', label: kioskCopy[locale].steps[1] },
    { id: 'payment', label: kioskCopy[locale].steps[2] },
    { id: 'result', label: kioskCopy[locale].steps[3] },
  ];
}

interface CheckoutSessionSnapshot {
  version: 1;
  savedAt: number;
  step: CheckoutStep;
  cart: CartLine[];
  quote: Quote | null;
  order: KioskOrder | null;
  paymentMethod: PaymentMethod;
  fulfillmentType: FulfillmentType;
  orderIdempotencyKey: string | null;
  retryIdempotencyKey: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function validCheckoutSnapshot(value: unknown): value is CheckoutSessionSnapshot {
  if (!isRecord(value) || value.version !== 1 || typeof value.savedAt !== 'number') return false;
  if (!['browse', 'review', 'payment', 'result'].includes(String(value.step))) return false;
  if (!['CARD', 'CONTACTLESS', 'APPLE_PAY', 'GOOGLE_PAY'].includes(String(value.paymentMethod))) {
    return false;
  }
  if (!['DINE_IN', 'TAKEAWAY'].includes(String(value.fulfillmentType))) return false;
  if (!Array.isArray(value.cart)) return false;
  if (value.quote !== null && !isRecord(value.quote)) return false;
  if (value.order !== null && !isRecord(value.order)) return false;
  if (value.orderIdempotencyKey !== null && typeof value.orderIdempotencyKey !== 'string') {
    return false;
  }
  return value.retryIdempotencyKey === null || typeof value.retryIdempotencyKey === 'string';
}

function toStoredCart(cart: CartLine[]): CartLine[] {
  return cart.map((line) => ({
    ...line,
    product: { ...line.product, image_url: null },
  }));
}

function sanitizeCheckoutSnapshot(snapshot: CheckoutSessionSnapshot): CheckoutSessionSnapshot {
  return {
    ...snapshot,
    cart: toStoredCart(snapshot.cart),
  };
}

function clearCheckoutSession(): void {
  try {
    window.sessionStorage.removeItem(CHECKOUT_SESSION_KEY);
  } catch {
    // The checkout still works if browser storage is unavailable.
  }
}

function readCheckoutSession(): CheckoutSessionSnapshot | null {
  try {
    const stored = window.sessionStorage.getItem(CHECKOUT_SESSION_KEY);
    if (!stored) return null;
    const snapshot: unknown = JSON.parse(stored);
    if (!validCheckoutSnapshot(snapshot)) {
      clearCheckoutSession();
      return null;
    }
    if (!snapshot.order && Date.now() - snapshot.savedAt > CHECKOUT_SESSION_MAX_AGE_MS) {
      clearCheckoutSession();
      return null;
    }
    return snapshot;
  } catch {
    clearCheckoutSession();
    return null;
  }
}

function writeCheckoutSession(snapshot: CheckoutSessionSnapshot): void {
  try {
    window.sessionStorage.setItem(
      CHECKOUT_SESSION_KEY,
      JSON.stringify(sanitizeCheckoutSnapshot(snapshot)),
    );
  } catch {
    // Recovery is best-effort; payment idempotency remains enforced by the API.
  }
}

function recoveredStep(snapshot: CheckoutSessionSnapshot | null): CheckoutStep {
  if (!snapshot) return 'browse';
  if (snapshot.order) {
    return settledPaymentStatuses.has(snapshot.order.payment_status) ||
      terminalStatuses.has(snapshot.order.status)
      ? 'result'
      : 'payment';
  }
  return snapshot.quote ? 'review' : 'browse';
}

function toUserFacingError(error: unknown): UserFacingError {
  if (error instanceof ApiError) {
    const messages: Record<string, { title: string; message: string }> = {
      network_unavailable: {
        title: 'Geen verbinding',
        message: 'Controleer de lokale netwerkverbinding en probeer het opnieuw.',
      },
      request_timeout: {
        title: 'Dit duurt te lang',
        message:
          'De server reageerde niet op tijd. Controleer de status voordat je opnieuw betaalt.',
      },
      store_not_accepting_orders: {
        title: 'Bestellen is tijdelijk gepauzeerd',
        message: 'Vraag een medewerker om hulp of probeer het later opnieuw.',
      },
      fulfillment_unavailable: {
        title: 'De bar is niet beschikbaar',
        message: 'Er kan nu geen bestelling naar de bar worden gestuurd.',
      },
      fulfillment_station_unavailable: {
        title: 'De bar is nog niet gereed',
        message: 'Vraag een medewerker om het bereidingsscherm te controleren.',
      },
      fulfillment_station_ambiguous: {
        title: 'De barconfiguratie klopt niet',
        message: 'Vraag een medewerker om hulp voordat je betaalt.',
      },
      fulfillment_path_unavailable: {
        title: 'De bar is niet bereikbaar',
        message: 'Betalen is gepauzeerd totdat de bar weer verbonden is.',
      },
      fulfillment_queue_full: {
        title: 'Het is even erg druk',
        message:
          'Er kunnen nu geen extra bestellingen worden aangenomen. Probeer het later opnieuw.',
      },
      quote_expired: {
        title: 'Prijscontrole verlopen',
        message: 'Controleer je winkelmand opnieuw om de actuele prijs op te halen.',
      },
      payment_result_unknown: {
        title: 'Betaling wordt gecontroleerd',
        message:
          'Start geen nieuwe betaling. Gebruik “Controleer betaling” om dubbel betalen te voorkomen.',
      },
      payment_terminal_unavailable: {
        title: 'Betaalterminal niet beschikbaar',
        message: 'Vraag een medewerker om de betaalterminal te controleren.',
      },
      payment_adapter_unavailable: {
        title: 'Betalen tijdelijk niet beschikbaar',
        message: 'De betaaldienst is niet gereed. Vraag een medewerker om hulp.',
      },
      payment_adapter_mismatch: {
        title: 'Betaalterminal moet worden gecontroleerd',
        message: 'Vraag een medewerker om hulp. Start geen tweede bestelling.',
      },
      idempotency_request_in_progress: {
        title: 'Bestelling wordt verwerkt',
        message: 'Wacht even en controleer daarna de bestelstatus. Start geen nieuwe betaling.',
      },
      payment_not_reconcilable: {
        title: 'Status kan nu niet worden gecontroleerd',
        message: 'Vernieuw de bestelling of vraag een medewerker om hulp.',
      },
      payment_retry_not_allowed: {
        title: 'Opnieuw betalen is niet nodig',
        message: 'Controleer eerst de actuele bestelstatus.',
      },
      request_validation_failed: {
        title: 'Controleer je bestelling',
        message: 'Een onderdeel van de bestelling is niet meer geldig. Pas de bestelling aan.',
      },
      quote_not_active: {
        title: 'Prijscontrole verlopen',
        message: 'Ga terug naar het menu en controleer de bestelling opnieuw.',
      },
      product_not_priced: {
        title: 'Product tijdelijk niet beschikbaar',
        message: 'Verwijder dit product uit je bestelling en kies iets anders.',
      },
      sale_receipt_not_ready: {
        title: 'Betaalbewijs wordt voorbereid',
        message: 'Probeer het over enkele seconden opnieuw.',
      },
      not_found: {
        title: 'Bestelling niet gevonden',
        message: 'Vraag een medewerker om hulp en vermeld de referentie op dit scherm.',
      },
      unauthorized: {
        title: 'Kiosk niet gekoppeld',
        message:
          'De apparaatgegevens zijn ongeldig. Vraag een beheerder om de kiosk opnieuw te koppelen.',
      },
    };
    const mapped = messages[error.code];
    return {
      title: mapped?.title ?? 'Actie niet gelukt',
      message:
        mapped?.message ??
        'De actie kon niet veilig worden afgerond. Probeer het opnieuw of vraag een medewerker om hulp.',
      reference: error.correlationId,
    };
  }
  return {
    title: 'Onverwachte fout',
    message: 'Probeer het opnieuw. Vraag een medewerker om hulp als dit blijft gebeuren.',
    reference: null,
  };
}

function productLineKey(productId: string, optionValueIds: string[]): string {
  return `${productId}:${[...optionValueIds].sort().join(',')}`;
}

function firstProductCategory(catalog: StoreCatalog): string | null {
  return catalog.categories.find((category) => category.products.length > 0)?.id ?? null;
}

function ErrorNotice({ error, onRetry }: { error: UserFacingError; onRetry?: () => void }) {
  return (
    <section className="error-notice" role="alert">
      <span className="error-notice-mark" aria-hidden="true">
        !
      </span>
      <div>
        <strong>{error.title}</strong>
        <p>{error.message}</p>
        {error.reference && <small>Referentie: {error.reference}</small>}
      </div>
      {onRetry && (
        <button className="secondary-button" type="button" onClick={onRetry}>
          Opnieuw proberen
        </button>
      )}
    </section>
  );
}

export function App({ api: providedApi }: AppProps) {
  const [initialCheckout] = useState(readCheckoutSession);
  const [api, setApi] = useState<KioskApi | null>(() => providedApi ?? createConfiguredKioskApi());
  const [catalog, setCatalog] = useState<StoreCatalog | null>(null);
  // The customer ordering interface is always presented in Dutch (nl-NL).
  const [locale] = useState<'zh-CN' | 'nl-NL'>('nl-NL');
  const [selectedCategoryId, setSelectedCategoryId] = useState<string | null>(null);
  const [isCategoryMenuOpen, setIsCategoryMenuOpen] = useState(true);
  const [cart, setCart] = useState<CartLine[]>(() => initialCheckout?.cart ?? []);
  const [customizing, setCustomizing] = useState<CatalogProduct | null>(null);
  const [step, setStep] = useState<CheckoutStep>(() => recoveredStep(initialCheckout));
  const [quote, setQuote] = useState<Quote | null>(() => initialCheckout?.quote ?? null);
  const [order, setOrder] = useState<KioskOrder | null>(() => initialCheckout?.order ?? null);
  const [receipts, setReceipts] = useState<KioskReceipt[]>([]);
  const [storeStatus, setStoreStatus] = useState<KioskStoreStatus | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>('checking');
  const [statusBusy, setStatusBusy] = useState(false);
  const [paymentMethod, setPaymentMethod] = useState<PaymentMethod>(
    () => initialCheckout?.paymentMethod ?? 'CONTACTLESS',
  );
  const [fulfillmentType, setFulfillmentType] = useState<FulfillmentType>(
    () => initialCheckout?.fulfillmentType ?? 'DINE_IN',
  );
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<UserFacingError | null>(null);
  const orderKeyRef = useRef<string | null>(initialCheckout?.orderIdempotencyKey ?? null);
  const retryKeyRef = useRef<string | null>(initialCheckout?.retryIdempotencyKey ?? null);
  const sessionReadyRef = useRef(false);
  const restoredOrderIdRef = useRef<string | null>(null);
  const customizerTriggerRef = useRef<HTMLButtonElement | null>(null);
  const statusCheckInFlightRef = useRef(false);
  const heartbeatInFlightRef = useRef(false);
  const consecutiveStatusFailuresRef = useRef(0);

  const refreshDeviceStatus = useCallback(
    async (showBusy = false) => {
      if (!api || statusCheckInFlightRef.current) return;
      statusCheckInFlightRef.current = true;
      if (showBusy) setStatusBusy(true);

      if (!heartbeatInFlightRef.current) {
        heartbeatInFlightRef.current = true;
        void api.heartbeat().catch(() => undefined).finally(() => {
          heartbeatInFlightRef.current = false;
        });
      }

      try {
        const response = await api.getStoreStatus();
        setStoreStatus(response);
        consecutiveStatusFailuresRef.current = 0;
        setConnectionState('online');
      } catch {
        consecutiveStatusFailuresRef.current += 1;
        if (consecutiveStatusFailuresRef.current >= DEVICE_OFFLINE_FAILURE_THRESHOLD) {
          setConnectionState('offline');
        }
      } finally {
        statusCheckInFlightRef.current = false;
        if (showBusy) setStatusBusy(false);
      }
    },
    [api],
  );

  const loadCatalog = useCallback(async () => {
    if (!api) return;
    setBusyAction('catalog');
    setError(null);
    try {
      const response = await api.getCatalog(locale);
      setCatalog(response);
      setSelectedCategoryId(firstProductCategory(response));
    } catch (loadError) {
      setError(toUserFacingError(loadError));
    } finally {
      setBusyAction(null);
    }
  }, [api, locale]);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  useEffect(() => {
    if (!sessionReadyRef.current) {
      sessionReadyRef.current = true;
      return;
    }
    if (cart.length === 0 && !quote && !order) {
      clearCheckoutSession();
      return;
    }
    writeCheckoutSession({
      version: 1,
      savedAt: Date.now(),
      step,
      cart,
      quote,
      order,
      paymentMethod,
      fulfillmentType,
      orderIdempotencyKey: orderKeyRef.current,
      retryIdempotencyKey: retryKeyRef.current,
    });
  }, [cart, fulfillmentType, order, paymentMethod, quote, step]);

  useEffect(() => {
    if (!api) return;
    statusCheckInFlightRef.current = false;
    heartbeatInFlightRef.current = false;
    consecutiveStatusFailuresRef.current = 0;
    setConnectionState('checking');
    void refreshDeviceStatus();
    const timer = window.setInterval(() => void refreshDeviceStatus(), DEVICE_REFRESH_INTERVAL_MS);
    const markOffline = () => {
      consecutiveStatusFailuresRef.current = DEVICE_OFFLINE_FAILURE_THRESHOLD;
      setConnectionState('offline');
    };
    const reconnect = () => {
      setConnectionState((current) => current === 'offline' ? 'checking' : current);
      void refreshDeviceStatus();
    };
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') void refreshDeviceStatus();
    };
    window.addEventListener('offline', markOffline);
    window.addEventListener('online', reconnect);
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener('offline', markOffline);
      window.removeEventListener('online', reconnect);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
    };
  }, [api, refreshDeviceStatus]);

  useEffect(() => {
    if (!api || !order || step !== 'result' || terminalStatuses.has(order.status)) return;
    const timer = window.setInterval(() => {
      void api
        .getOrder(order.id)
        .then(async (updatedOrder) => {
          setOrder(updatedOrder);
          if (
            receipts.length === 0 ||
            updatedOrder.refunded_minor !== order.refunded_minor ||
            updatedOrder.payment_status === 'REFUNDED'
          ) {
            setReceipts(await api.getReceipts(updatedOrder.id));
          }
        })
        .catch(() => undefined);
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [api, order, receipts.length, step]);

  useEffect(() => {
    if (!api || !initialCheckout?.order) return;
    if (restoredOrderIdRef.current === initialCheckout.order.id) return;
    restoredOrderIdRef.current = initialCheckout.order.id;
    let cancelled = false;
    setBusyAction('restore-order');
    void api
      .getOrder(initialCheckout.order.id)
      .then(async (updatedOrder) => {
        if (cancelled) return;
        setOrder(updatedOrder);
        if (
          settledPaymentStatuses.has(updatedOrder.payment_status) ||
          terminalStatuses.has(updatedOrder.status)
        ) {
          setStep('result');
          setCart([]);
          try {
            const restoredReceipts = await api.getReceipts(updatedOrder.id);
            if (!cancelled) setReceipts(restoredReceipts);
          } catch {
            if (!cancelled) {
              setError({
                title: 'Betaalbewijs nog niet beschikbaar',
                message: 'De betaling is bewaard. Probeer het betaalbewijs opnieuw op te halen.',
                reference: null,
              });
            }
          }
        } else {
          setStep('payment');
        }
      })
      .catch((restoreError) => {
        if (!cancelled) setError(toUserFacingError(restoreError));
      })
      .finally(() => {
        if (!cancelled) setBusyAction(null);
      });
    return () => {
      cancelled = true;
    };
  }, [api, initialCheckout]);

  const selectedCategory =
    catalog?.categories.find((category) => category.id === selectedCategoryId) ??
    catalog?.categories[0] ??
    null;
  const copy = kioskCopy[locale];
  const checkoutSteps: Array<{ id: CheckoutStep; label: string }> = checkoutStepsFor(locale);
  const kineticMenuItems: KineticMenuItem[] = (catalog?.categories ?? []).map((category) => ({
    id: category.id,
    label: category.name,
    detail: locale === 'zh-CN' ? `${category.products.length} 种现调饮品` : `${category.products.length} vers bereide dranken`,
  }));
  const cartQuantity = cart.reduce((total, line) => total + line.quantity, 0);
  const estimatedProductTotal = cart.reduce((total, line) => total + cartLineTotal(line), 0);
  const estimatedPackagingFee =
    fulfillmentType === 'TAKEAWAY' && storeStatus?.takeaway_fee_enabled
      ? storeStatus.takeaway_fee_minor
      : 0;
  const estimatedTotal = estimatedProductTotal + estimatedPackagingFee;
  const activeCurrency = catalog?.currency ?? quote?.currency ?? order?.currency ?? 'EUR';
  const acceptingNewOrders = connectionState === 'online' && storeStatus?.accepting_orders === true;
  const newOrderStep = step === 'browse' || step === 'review';
  const currentStepIndex = checkoutSteps.findIndex((item) => item.id === step);
  const canResetOrder =
    busyAction === null &&
    (step === 'browse' ||
      step === 'review' ||
      step === 'result' ||
      (step === 'payment' && order?.payment_status === 'FAILED'));

  const cartRequest = useMemo(
    () =>
      cart.map((line) => ({
        product_id: line.product.id,
        quantity: line.quantity,
        option_value_ids: line.optionValueIds,
      })),
    [cart],
  );

  function configureDevice(config: KioskRuntimeConfig) {
    setApi(new KioskApiClient(config));
  }

  function disconnectDevice() {
    clearSessionKioskConfig();
    setApi(null);
    setCatalog(null);
    setStoreStatus(null);
    setConnectionState('checking');
    newOrder();
  }

  function addToCart(product: CatalogProduct, optionValueIds: string[]) {
    if (cartQuantity >= 100) {
      setError({
        title: 'Maximaal 100 producten',
        message: 'Verlaag eerst een aantal voordat je nog een product toevoegt.',
        reference: null,
      });
      setCustomizing(null);
      return;
    }
    const allOptions = product.option_groups.flatMap((group) =>
      group.values.map((value) => ({ groupName: group.name, value })),
    );
    const selectedOptions = allOptions.filter((option) => optionValueIds.includes(option.value.id));
    const key = productLineKey(product.id, optionValueIds);
    setCart((current) => {
      const currentQuantity = current.reduce((total, line) => total + line.quantity, 0);
      if (currentQuantity >= 100) return current;
      const existing = current.find((line) => line.key === key);
      if (existing) {
        return current.map((line) =>
          line.key === key
            ? {
                ...line,
                quantity: Math.min(line.quantity + 1, 20, line.quantity + (100 - currentQuantity)),
              }
            : line,
        );
      }
      return [...current, { key, product, optionValueIds, selectedOptions, quantity: 1 }];
    });
    setError(null);
    setCustomizing(null);
  }

  function chooseProduct(product: CatalogProduct) {
    if (!acceptingNewOrders) return;
    if (product.option_groups.length === 0) {
      addToCart(product, []);
    } else {
      setCustomizing(product);
    }
  }

  function closeCustomizer() {
    setCustomizing(null);
    window.requestAnimationFrame(() => customizerTriggerRef.current?.focus());
  }

  function changeQuantity(key: string, delta: number) {
    if (delta > 0 && cartQuantity >= 100) {
      setError({
        title: 'Maximaal 100 producten',
        message: 'Verlaag eerst een aantal voordat je nog een product toevoegt.',
        reference: null,
      });
      return;
    }
    setCart((current) => {
      const currentQuantity = current.reduce((total, line) => total + line.quantity, 0);
      return current
        .map((line) =>
          line.key === key
            ? {
                ...line,
                quantity: Math.max(
                  0,
                  Math.min(20, line.quantity + delta, line.quantity + (100 - currentQuantity)),
                ),
              }
            : line,
        )
        .filter((line) => line.quantity > 0);
    });
    setQuote(null);
    orderKeyRef.current = null;
  }

  async function reviewOrder() {
    if (!api || cart.length === 0 || !acceptingNewOrders) return;
    setBusyAction('quote');
    setError(null);
    try {
      const response = await api.createQuote(locale, cartRequest, fulfillmentType);
      setQuote(response);
      setStep('review');
      orderKeyRef.current = null;
    } catch (quoteError) {
      setError(toUserFacingError(quoteError));
    } finally {
      setBusyAction(null);
    }
  }

  async function startPayment() {
    if (!api || !quote || !acceptingNewOrders) return;
    const idempotencyKey = orderKeyRef.current ?? createIdempotencyKey('order');
    orderKeyRef.current = idempotencyKey;
    setBusyAction('create-order');
    setError(null);
    writeCheckoutSession({
      version: 1,
      savedAt: Date.now(),
      step: 'review',
      cart,
      quote,
      order: null,
      paymentMethod,
      fulfillmentType,
      orderIdempotencyKey: idempotencyKey,
      retryIdempotencyKey: retryKeyRef.current,
    });
    try {
      const created = await api.createOrder(quote.id, paymentMethod, idempotencyKey);
      setOrder(created);
      setStep('payment');
      writeCheckoutSession({
        version: 1,
        savedAt: Date.now(),
        step: 'payment',
        cart,
        quote,
        order: created,
        paymentMethod,
        fulfillmentType,
        orderIdempotencyKey: idempotencyKey,
        retryIdempotencyKey: retryKeyRef.current,
      });
      const attempt = latestPaymentAttempt(created);
      if (!attempt) throw new Error('Order has no payment attempt.');
      await executeAttempt(attempt.id, created.id);
    } catch (paymentError) {
      setError(toUserFacingError(paymentError));
    } finally {
      setBusyAction(null);
    }
  }

  async function showPaidOrder(paidOrder: KioskOrder) {
    if (!api) return;
    setOrder(paidOrder);
    setStep('result');
    setCart([]);
    setError(null);
    writeCheckoutSession({
      version: 1,
      savedAt: Date.now(),
      step: 'result',
      cart: [],
      quote: null,
      order: paidOrder,
      paymentMethod,
      fulfillmentType,
      orderIdempotencyKey: orderKeyRef.current,
      retryIdempotencyKey: retryKeyRef.current,
    });
    try {
      setReceipts(await api.getReceipts(paidOrder.id));
    } catch (receiptError) {
      setError(toUserFacingError(receiptError));
    }
  }

  async function executeAttempt(attemptId: string, knownOrderId: string) {
    if (!api) return;
    setBusyAction('execute-payment');
    setError(null);
    try {
      const response = await api.executePayment(attemptId);
      setOrder(response);
      if (response.payment_status === 'PAID') {
        await showPaidOrder(response);
      } else if (response.payment_status === 'FAILED') {
        setStep('payment');
      } else if (response.payment_status === 'UNKNOWN') {
        setStep('payment');
      }
    } catch (executeError) {
      setError(toUserFacingError(executeError));
      try {
        const recoveredOrder = await api.getOrder(knownOrderId);
        setOrder(recoveredOrder);
        if (recoveredOrder.payment_status === 'PAID') {
          await showPaidOrder(recoveredOrder);
        }
      } catch {
        // Keep the known order visible so the customer cannot accidentally start over.
      }
    } finally {
      setBusyAction(null);
    }
  }

  async function reconcilePayment() {
    if (!api || !order) return;
    const attempt = latestPaymentAttempt(order);
    if (!attempt) return;
    setBusyAction('reconcile');
    setError(null);
    try {
      const response = await api.reconcilePayment(attempt.id);
      setOrder(response);
      if (response.payment_status === 'PAID') {
        await showPaidOrder(response);
      }
    } catch (reconcileError) {
      setError(toUserFacingError(reconcileError));
    } finally {
      setBusyAction(null);
    }
  }

  async function retryPayment() {
    if (!api || !order || order.payment_status !== 'FAILED') return;
    const idempotencyKey = retryKeyRef.current ?? createIdempotencyKey('retry');
    retryKeyRef.current = idempotencyKey;
    setBusyAction('retry-payment');
    setError(null);
    writeCheckoutSession({
      version: 1,
      savedAt: Date.now(),
      step: 'payment',
      cart,
      quote,
      order,
      paymentMethod,
      fulfillmentType,
      orderIdempotencyKey: orderKeyRef.current,
      retryIdempotencyKey: idempotencyKey,
    });
    try {
      const response = await api.retryPayment(order.id, paymentMethod, idempotencyKey);
      setOrder(response);
      writeCheckoutSession({
        version: 1,
        savedAt: Date.now(),
        step: 'payment',
        cart,
        quote,
        order: response,
        paymentMethod,
        fulfillmentType,
        orderIdempotencyKey: orderKeyRef.current,
        retryIdempotencyKey: idempotencyKey,
      });
      const attempt = latestPaymentAttempt(response);
      if (!attempt) throw new Error('Order has no retry payment attempt.');
      await executeAttempt(attempt.id, response.id);
      retryKeyRef.current = null;
    } catch (retryError) {
      setError(toUserFacingError(retryError));
    } finally {
      setBusyAction(null);
    }
  }

  async function refreshOrder() {
    if (!api || !order) return;
    setBusyAction('refresh-order');
    setError(null);
    try {
      const response = await api.getOrder(order.id);
      setOrder(response);
      if (response.payment_status === 'PAID' && receipts.length === 0) {
        await showPaidOrder(response);
      } else if (step === 'result') {
        setReceipts(await api.getReceipts(response.id));
      }
    } catch (refreshError) {
      setError(toUserFacingError(refreshError));
    } finally {
      setBusyAction(null);
    }
  }

  async function retryReceipts() {
    if (!api || !order) return;
    setBusyAction('receipts');
    setError(null);
    try {
      setReceipts(await api.getReceipts(order.id));
    } catch (receiptError) {
      setError(toUserFacingError(receiptError));
    } finally {
      setBusyAction(null);
    }
  }

  function newOrder() {
    setCart([]);
    setQuote(null);
    setOrder(null);
    setReceipts([]);
    setError(null);
    setStep('browse');
    setFulfillmentType('DINE_IN');
    setIsCategoryMenuOpen(true);
    clearCheckoutSession();
    orderKeyRef.current = null;
    retryKeyRef.current = null;
  }

  if (!api) {
    return <DeviceSetup onConfigured={configureDevice} />;
  }

  if (!catalog && busyAction === 'catalog') {
    return (
      <main className="loading-page" aria-live="polite" aria-busy="true">
        <div className="spinner" aria-hidden="true" />
        <h1>{copy.loading}</h1>
        <p>{copy.wait}</p>
      </main>
    );
  }

  if (!catalog) {
    return (
      <main className="loading-page">
        <h1>{copy.unavailable}</h1>
        {error && <ErrorNotice error={error} onRetry={() => void loadCatalog()} />}
        {!providedApi && (
          <button className="text-button" type="button" onClick={disconnectDevice}>
            {copy.device}
          </button>
        )}
      </main>
    );
  }

  return (
    <div className="kiosk-shell">
      <header className="topbar">
        <button
          className="brand-button"
          type="button"
          onClick={newOrder}
          disabled={!canResetOrder}
          aria-label={copy.brand}
        >
          {catalog?.logo_url ? (
            <img className="brand-logo" src={catalog.logo_url} alt="" aria-hidden="true" />
          ) : (
            <span className="brand-mark" aria-hidden="true">
              S
            </span>
          )}
          <span>
            <strong>{catalog?.merchant_name ?? 'SipPilot'}</strong>
            <small>{catalog?.store_name ?? copy.brand}</small>
          </span>
        </button>
        <ol className="step-indicator" aria-label={copy.progress}>
          {checkoutSteps.map((item, index) => (
            <li
              className={step === item.id ? 'active' : index < currentStepIndex ? 'complete' : ''}
              key={item.id}
              aria-current={step === item.id ? 'step' : undefined}
            >
              <span>{index < currentStepIndex ? '✓' : index + 1}</span>
              <small>{item.label}</small>
            </li>
          ))}
        </ol>
        <div className="topbar-actions">
          <span
            className={`connection-pill connection-${connectionState}`}
            aria-live="polite"
            title={
              connectionState === 'online'
                ? 'Kiosk is verbonden met de lokale service'
                : 'Verbinding met de lokale service wordt gecontroleerd'
            }
          >
            <span aria-hidden="true" />
            {connectionState === 'checking'
              ? copy.checking
              : connectionState === 'online'
                ? copy.online
                : copy.offline}
          </span>
          {!providedApi && (
            <button
              className="text-button"
              type="button"
              onClick={disconnectDevice}
              disabled={!canResetOrder}
            >
              {copy.changeKiosk}
            </button>
          )}
        </div>
      </header>

      {error && <ErrorNotice error={error} />}

      {newOrderStep && connectionState !== 'checking' && !acceptingNewOrders && (
        <section className="service-banner" role="status" aria-live="polite">
          <span className="service-banner-mark" aria-hidden="true">
            {connectionState === 'offline' ? '⌁' : 'Ⅱ'}
          </span>
          <div>
            <strong>
              {connectionState === 'offline'
                ? 'Bestellen is tijdelijk niet beschikbaar'
                : copy.paused}
            </strong>
            <p>
              {connectionState === 'offline'
                ? 'De kiosk kan de lokale service niet bereiken. Controleer de verbinding of vraag een medewerker om hulp.'
                : copy.pausedDetail}
            </p>
          </div>
          <button
            className="secondary-button"
            type="button"
            disabled={statusBusy}
            onClick={() => void refreshDeviceStatus(true)}
          >
            {statusBusy ? `${copy.checking}…` : copy.retry}
          </button>
        </section>
      )}

      {step === 'browse' && (
        <>
          <SterlingGateKineticNavigation
            isOpen={isCategoryMenuOpen}
            items={kineticMenuItems}
            language={locale}
            onClose={() => setIsCategoryMenuOpen(false)}
            onSelect={(categoryId) => {
              setSelectedCategoryId(categoryId);
              setIsCategoryMenuOpen(false);
            }}
          />
          <main className="ordering-layout">
          <aside className="category-panel" aria-label="Categorieën">
            <p className="category-kicker">{copy.assortment}</p>
            <h2>{copy.menu}</h2>
            <nav>
              {catalog.categories.map((category) => (
                <button
                  type="button"
                  className={selectedCategory?.id === category.id ? 'active' : ''}
                  key={category.id}
                  onClick={() => setSelectedCategoryId(category.id)}
                >
                  {category.name}
                  <span>{category.products.length}</span>
                </button>
              ))}
            </nav>
          </aside>

          <section className="product-section" aria-labelledby="category-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">{copy.freshlyMade}</p>
                <h1 id="category-title">{selectedCategory?.name ?? copy.menu}</h1>
              </div>
              <div className="category-heading-actions">
                <button
                  className="open-category-menu"
                  type="button"
                  onClick={() => setIsCategoryMenuOpen(true)}
                >
                  {copy.explore}
                </button>
                <p>{selectedCategory?.products.length ?? 0} {copy.choices}</p>
              </div>
            </div>
            <div className="product-grid">
              {selectedCategory?.products.map((product) => {
                const allergens = allergenNames(product.allergen_data);
                return (
                  <article className="product-card" key={product.id}>
                    {product.image_url ? (
                      <img src={product.image_url} alt="" />
                    ) : (
                      <div className="product-placeholder" aria-hidden="true">
                        ☕
                      </div>
                    )}
                    <div className="product-copy">
                      <h2>{product.name}</h2>
                      {product.description && <p>{product.description}</p>}
                      {product.option_groups.length > 0 && <small className="customizable-badge">{copy.customizable}</small>}
                      {allergens.length > 0 && <small>Bevat: {allergens.join(', ')}</small>}
                    </div>
                    <div className="product-footer">
                      <strong>{formatMoney(product.price_minor, product.currency, locale)}</strong>
                      <button
                        type="button"
                        onClick={(event) => {
                          customizerTriggerRef.current = event.currentTarget;
                          chooseProduct(product);
                        }}
                        disabled={busyAction !== null || !acceptingNewOrders}
                        aria-label={`${product.name} toevoegen`}
                      >
                        <span aria-hidden="true">+</span>
                        <span>{copy.add}</span>
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          </section>

          <aside className="cart-panel" aria-labelledby="cart-title">
            <div className="cart-heading">
              <div>
                <p>{copy.cart}</p>
                <h2 id="cart-title">{copy.order}</h2>
              </div>
              <span aria-label={`${cartQuantity} producten`}>{cartQuantity}</span>
            </div>
            {cart.length === 0 ? (
              <div className="empty-cart">
                <span aria-hidden="true">＋</span>
                <p>{copy.emptyCart}</p>
              </div>
            ) : (
              <ul className="cart-lines">
                {cart.map((line) => (
                  <li key={line.key}>
                    <div>
                      <strong>{line.product.name}</strong>
                      {line.selectedOptions.length > 0 && (
                        <small>
                          {line.selectedOptions.map((option) => option.value.name).join(', ')}
                        </small>
                      )}
                    </div>
                    <div className="cart-line-actions">
                      <div className="quantity-control" aria-label={`Aantal ${line.product.name}`}>
                        <button
                          type="button"
                          onClick={() => changeQuantity(line.key, -1)}
                          disabled={busyAction !== null || !acceptingNewOrders}
                          aria-label={`Eén ${line.product.name} minder`}
                        >
                          −
                        </button>
                        <span>{line.quantity}</span>
                        <button
                          type="button"
                          onClick={() => changeQuantity(line.key, 1)}
                          disabled={busyAction !== null || !acceptingNewOrders}
                          aria-label={`Eén ${line.product.name} meer`}
                        >
                          +
                        </button>
                      </div>
                      <strong>{formatMoney(cartLineTotal(line), activeCurrency, locale)}</strong>
                    </div>
                  </li>
                ))}
              </ul>
            )}
            <div className="cart-summary">
              <fieldset className="fulfillment-choice">
                <legend>Waar geniet je van je bestelling?</legend>
                <label className={fulfillmentType === 'DINE_IN' ? 'selected' : ''}>
                  <input
                    type="radio"
                    name="fulfillment-type"
                    value="DINE_IN"
                    checked={fulfillmentType === 'DINE_IN'}
                    onChange={() => {
                      setFulfillmentType('DINE_IN');
                      setQuote(null);
                    }}
                  />
                  <span>Hier eten</span>
                  <small>Geen verpakkingskosten</small>
                </label>
                <label className={fulfillmentType === 'TAKEAWAY' ? 'selected' : ''}>
                  <input
                    type="radio"
                    name="fulfillment-type"
                    value="TAKEAWAY"
                    checked={fulfillmentType === 'TAKEAWAY'}
                    onChange={() => {
                      setFulfillmentType('TAKEAWAY');
                      setQuote(null);
                    }}
                  />
                  <span>Meenemen</span>
                  <small>
                    {estimatedPackagingFee > 0
                      ? `Verpakking ${formatMoney(estimatedPackagingFee, activeCurrency, locale)}`
                      : 'Geen verpakkingskosten'}
                  </small>
                </label>
              </fieldset>
              <p>
                <span>{copy.estimated}</span>
                <strong>{formatMoney(estimatedTotal, activeCurrency, locale)}</strong>
              </p>
              <small>{copy.vat}</small>
              <button
                className="primary-button"
                type="button"
                disabled={cart.length === 0 || busyAction !== null || !acceptingNewOrders}
                onClick={() => void reviewOrder()}
              >
                {busyAction === 'quote' ? `${copy.checking}…` : copy.review}
              </button>
            </div>
          </aside>
          </main>
        </>
      )}

      {step === 'review' && quote && (
        <main className="checkout-page">
          <section className="checkout-card" aria-labelledby="review-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow">{locale === 'zh-CN' ? '订单确认' : 'Controle'}</p>
                <h1 id="review-title">{copy.checkOrder}</h1>
              </div>
              <button
                className="secondary-button"
                type="button"
                onClick={() => setStep('browse')}
                disabled={busyAction !== null}
              >
                {copy.edit}
              </button>
            </div>
            <ul className="review-lines">
              {quote.items.map((item) => (
                <li key={item.line_number}>
                  <div>
                    <strong>
                      {item.quantity}× {item.name}
                    </strong>
                    {item.options.length > 0 && (
                      <small>{item.options.map((option) => option.name).join(', ')}</small>
                    )}
                  </div>
                  <strong>
                    {formatMoney(item.line_total_minor, quote.currency, quote.locale)}
                  </strong>
                </li>
              ))}
            </ul>
            <p className="fulfillment-summary">
              <strong>{quote.fulfillment_type === 'TAKEAWAY' ? 'Meenemen' : 'Hier eten'}</strong>
            </p>
            <div className="totals">
              {quote.packaging_fee_minor > 0 && (
                <p>
                  <span>Verpakkingskosten</span>
                  <span>{formatMoney(quote.packaging_fee_minor, quote.currency, quote.locale)}</span>
                </p>
              )}
              <p>
                <span>{copy.subtotal}</span>
                <span>{formatMoney(quote.subtotal_minor, quote.currency, quote.locale)}</span>
              </p>
              {quote.discount_minor > 0 && (
                <p className="discount">
                  <span>{copy.discount}</span>
                  <span>− {formatMoney(quote.discount_minor, quote.currency, quote.locale)}</span>
                </p>
              )}
              <p>
                <span>{copy.tax}</span>
                <span>{formatMoney(quote.tax_minor, quote.currency, quote.locale)}</span>
              </p>
              <p className="grand-total">
                <span>{copy.total}</span>
                <strong>{formatMoney(quote.total_minor, quote.currency, quote.locale)}</strong>
              </p>
              <small>
                {quote.prices_include_tax
                  ? copy.taxIncluded
                  : copy.taxAdded}
              </small>
            </div>
            <fieldset className="payment-methods">
              <legend>{copy.paymentHow}</legend>
              <label className={paymentMethod === 'CONTACTLESS' ? 'selected' : ''}>
                <input
                  type="radio"
                  name="payment"
                  value="CONTACTLESS"
                  checked={paymentMethod === 'CONTACTLESS'}
                  onChange={() => setPaymentMethod('CONTACTLESS')}
                  disabled={busyAction !== null}
                />
                <span>{copy.contactless}</span>
                <small>{copy.contactlessHint}</small>
              </label>
              <label className={paymentMethod === 'CARD' ? 'selected' : ''}>
                <input
                  type="radio"
                  name="payment"
                  value="CARD"
                  checked={paymentMethod === 'CARD'}
                  onChange={() => setPaymentMethod('CARD')}
                  disabled={busyAction !== null}
                />
                <span>{copy.card}</span>
                <small>{copy.cardHint}</small>
              </label>
            </fieldset>
            <button
              className="primary-button checkout-button"
              type="button"
              disabled={busyAction !== null || !acceptingNewOrders}
              onClick={() => void startPayment()}
            >
              {busyAction
                ? `${copy.pay}…`
                : `${copy.pay} · ${formatMoney(quote.total_minor, quote.currency, quote.locale)}`}
            </button>
          </section>
        </main>
      )}

      {step === 'payment' && order && (
        <main className="payment-page">
          <section className="payment-card" aria-live="polite" aria-busy={busyAction !== null}>
            <div
              className={`payment-state payment-${order.payment_status.toLowerCase()}`}
              aria-hidden="true"
            >
              {order.payment_status === 'PAID'
                ? '✓'
                : order.payment_status === 'FAILED'
                  ? '!'
                  : '↻'}
            </div>
            <p className="eyebrow">{locale === 'zh-CN' ? '订单' : 'Bestelling'} {order.display_number}</p>
            <h1>{paymentStatusLabel(order.payment_status)}</h1>
            {busyAction === 'execute-payment' && (
              <p>{copy.processing}</p>
            )}
            {busyAction === null && order.payment_status === 'INITIATED' && (
              <p>De betaling is nog niet naar de terminal gestuurd. Je kunt veilig doorgaan.</p>
            )}
            {order.payment_status === 'AUTHORIZING' && (
              <p>
                De terminal heeft de betaling ontvangen. Controleer de status voordat je verdergaat.
              </p>
            )}
            {order.payment_status === 'UNKNOWN' && (
              <p>We weten nog niet zeker of de betaling is gelukt. Start geen nieuwe betaling.</p>
            )}
            {order.payment_status === 'FAILED' && (
              <p>Er is niets afgeschreven. Je kunt dezelfde bestelling opnieuw betalen.</p>
            )}
            <strong className="payment-amount">
              {formatMoney(order.total_minor, order.currency, order.locale)}
            </strong>
            <p>{order.fulfillment_type === 'TAKEAWAY' ? 'Meenemen' : 'Hier eten'}</p>
            <div className="payment-actions">
              {order.payment_status === 'INITIATED' && latestPaymentAttempt(order) && (
                <button
                  className="primary-button"
                  type="button"
                  disabled={busyAction !== null}
                  onClick={() => {
                    const attempt = latestPaymentAttempt(order);
                    if (attempt) void executeAttempt(attempt.id, order.id);
                  }}
                >
                  {busyAction === 'execute-payment' ? 'Betaling starten…' : 'Betaling hervatten'}
                </button>
              )}
              {(order.payment_status === 'UNKNOWN' || order.payment_status === 'AUTHORIZING') && (
                <button
                  className="primary-button"
                  type="button"
                  disabled={busyAction !== null}
                  onClick={() => void reconcilePayment()}
                >
                  {busyAction === 'reconcile' ? 'Controleren…' : 'Controleer betaling'}
                </button>
              )}
              {order.payment_status === 'FAILED' && (
                <button
                  className="primary-button"
                  type="button"
                  disabled={busyAction !== null}
                  onClick={() => void retryPayment()}
                >
                  {busyAction ? 'Opnieuw starten…' : 'Opnieuw betalen'}
                </button>
              )}
              <button
                className="secondary-button"
                type="button"
                disabled={busyAction !== null}
                onClick={() => void refreshOrder()}
              >
                {copy.refresh}
              </button>
            </div>
          </section>
        </main>
      )}

      {step === 'result' && order && (
        <main className="result-page">
          <section className="order-success" aria-labelledby="success-title">
            <div
              className={`success-mark ${order.status === 'CANCELLED' ? 'cancelled' : ''}`}
              aria-hidden="true"
            >
              {order.status === 'CANCELLED' ? '!' : '✓'}
            </div>
            <p className="eyebrow">
              {order.payment_status === 'REFUNDED'
                ? (locale === 'zh-CN' ? '退款已处理' : 'Terugbetaling verwerkt')
                : copy.received}
            </p>
            <h1 id="success-title">
              {order.status === 'CANCELLED' ? (locale === 'zh-CN' ? '订单已取消' : 'Bestelling geannuleerd') : copy.thankYou}
            </h1>
            <p>
              {order.status === 'CANCELLED'
                ? 'Bekijk hieronder het betaal- en terugbetalingsbewijs.'
                : order.status === 'CLOSED'
                  ? 'Je bestelling is afgerond.'
                  : copy.preparing}
            </p>
            {order.status !== 'CANCELLED' && (
              <div className="pickup-number">
                <span>{copy.pickup}</span>
                <strong>{order.display_number}</strong>
              </div>
            )}
            <p className="order-status">
              Bestelstatus:{' '}
              <strong>
                {order.status === 'CLOSED'
                  ? 'Afgerond'
                  : order.status === 'CANCELLED'
                    ? 'Geannuleerd'
                    : 'In voorbereiding'}
              </strong>
            </p>
            <p className="fulfillment-summary">
              {order.fulfillment_type === 'TAKEAWAY' ? 'Meenemen' : 'Hier eten'}
            </p>
            <button
              className="secondary-button"
              type="button"
              disabled={busyAction !== null}
              onClick={() => void refreshOrder()}
            >
              {copy.refresh}
            </button>
          </section>
          <div className="receipt-column">
            {receipts.length === 0 ? (
              <section className="receipt-loading" aria-live="polite">
                <strong>Betaalbewijs wordt opgehaald</strong>
                <p>Je betaling en afhaalnummer zijn veilig bewaard.</p>
                <button
                  className="secondary-button"
                  type="button"
                  disabled={busyAction !== null}
                  onClick={() => void retryReceipts()}
                >
                  {busyAction === 'receipts' ? 'Ophalen…' : 'Betaalbewijs opnieuw ophalen'}
                </button>
              </section>
            ) : (
              receipts.map((receipt) => (
                <ReceiptView
                  key={`${receipt.receipt_type}-${receipt.receipt_number}`}
                  receipt={receipt}
                  language={locale}
                />
              ))
            )}
            <button className="primary-button" type="button" onClick={newOrder}>
              {locale === 'zh-CN' ? '开始新订单' : 'Nieuwe bestelling'}
            </button>
          </div>
        </main>
      )}

      {customizing && (
        <ProductCustomizer
          product={customizing}
          locale={locale}
          language={locale}
          onCancel={closeCustomizer}
          onAdd={(ids) => addToCart(customizing, ids)}
        />
      )}
    </div>
  );
}
