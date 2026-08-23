import { useCallback, useRef, useState, type FormEvent } from 'react';
import { createIdempotencyKey, type ApiClient } from '../api';
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
import { formText } from '../form';
import { formatDateTime, parseJsonObject, parseMajorMoney, shortId } from '../format';
import { useAsyncResource } from '../hooks';
import type { ManualReview } from '../types';
import { useAdminI18n } from '../i18n';

const RESOLUTIONS = [
  'FULL_REFUND',
  'PARTIAL_REFUND',
  'REMAKE',
  'SUBSTITUTION',
  'MANUALLY_FULFILLED',
  'NO_FINANCIAL_ACTION',
];

export function ReviewsPage({
  api,
  canResolve,
  currentUserId,
}: {
  api: ApiClient;
  canResolve: boolean;
  currentUserId: string;
}) {
  const { choose } = useAdminI18n();
  const loader = useCallback(() => api.get<ManualReview[]>('/admin/reviews?limit=200'), [api]);
  const resource = useAsyncResource(loader);
  const [selected, setSelected] = useState<ManualReview | null>(null);
  const [pending, setPending] = useState(false);
  const [mutationError, setMutationError] = useState<unknown>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const resolutionKey = useRef<{ reviewId: string; version: number; key: string } | null>(null);

  const replace = (updated: ManualReview) => {
    resource.setData(
      (current) => current?.map((entry) => (entry.id === updated.id ? updated : entry)) ?? null,
    );
    setSelected(updated);
  };
  const assignToMe = (review: ManualReview) => {
    setMutationError(null);
    setSuccess(null);
    void api
      .post<ManualReview>(`/admin/reviews/${review.id}/assign`, {
        expected_version: review.version,
        assignee_user_id: currentUserId,
      })
      .then((updated) => {
        replace(updated);
        setSuccess(choose(`案件 ${updated.case_number} 已分配给你。`, `Dossier ${updated.case_number} is aan jou toegewezen.`));
      }, setMutationError);
  };
  const resolve = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selected) return;
    const form = event.currentTarget;
    const resolution = formText(form, 'resolution');
    const refundText = formText(form, 'refund_amount');
    setPending(true);
    setMutationError(null);
    setSuccess(null);
    let payload: Record<string, unknown>;
    let refundAmount: number | null;
    try {
      payload = parseJsonObject(formText(form, 'payload'), 'Payload');
      refundAmount = resolution === 'PARTIAL_REFUND' ? parseMajorMoney(refundText) : null;
    } catch (error) {
      setPending(false);
      setMutationError(error);
      return;
    }
    void api
      .post<ManualReview>(
        `/admin/reviews/${selected.id}/resolve`,
        {
          expected_version: selected.version,
          resolution,
          refund_amount_minor: refundAmount,
          notes: formText(form, 'notes'),
          payload,
        },
        {
          'Idempotency-Key': (() => {
            const current = resolutionKey.current;
            if (current?.reviewId === selected.id && current.version === selected.version) {
              return current.key;
            }
            const key = createIdempotencyKey('manual-review');
            resolutionKey.current = { reviewId: selected.id, version: selected.version, key };
            return key;
          })(),
        },
      )
      .then(
        (updated) => {
          replace(updated);
          resolutionKey.current = null;
          setPending(false);
          setSuccess(choose(`案件 ${updated.case_number} 已处理。`, `Dossier ${updated.case_number} is afgehandeld.`));
        },
        (error: unknown) => {
          setPending(false);
          setMutationError(error);
        },
      );
  };

  return (
    <section>
      <PageHeader
        title={choose('人工审核', 'Handmatige beoordeling')}
        description={choose('处理无法履约订单及财务补救事项的人工审核队列。', 'Behandel uitzonderingen voor niet-uitvoerbare bestellingen en financiële correcties.')}
      />
      <MutationMessage error={mutationError} success={success} />
      {resource.loading ? <LoadingState label={choose('正在加载人工审核…', 'Handmatige beoordelingen laden…')} /> : null}
      {resource.error ? <ErrorState error={resource.error} retry={resource.reload} /> : null}
      {resource.data?.length === 0 ? (
        <EmptyState
          title={choose('审核队列为空', 'Beoordelingswachtrij is leeg')}
          detail={choose('当前没有等待处理的人工审核事项。', 'Er wachten momenteel geen beoordelingen op afhandeling.')}
        />
      ) : null}
      {resource.data?.length ? (
        <div className="card-grid">
          {resource.data.map((review) => (
            <article className="card" key={review.id}>
              <header className="card-header">
                <div>
                  <h2>{review.case_number}</h2>
                  <p>
                    {review.reason_code} · {choose('优先级', 'prioriteit')} {review.priority}
                  </p>
                </div>
                <StatusBadge value={review.status} />
              </header>
              <dl className="definition-grid">
                <div>
                  <dt>{choose('订单', 'Bestelling')}</dt>
                  <dd className="monospace">{shortId(review.order_id)}</dd>
                </div>
                <div>
                  <dt>{choose('负责人', 'Toegewezen aan')}</dt>
                  <dd>{review.assigned_to ? shortId(review.assigned_to) : choose('未分配', 'Niet toegewezen')}</dd>
                </div>
                <div>
                  <dt>{choose('分配时间', 'Toegewezen op')}</dt>
                  <dd>{formatDateTime(review.assigned_at)}</dd>
                </div>
                <div>
                  <dt>{choose('版本', 'Versie')}</dt>
                  <dd>{review.version}</dd>
                </div>
              </dl>
              {canResolve && !['RESOLVED', 'CLOSED'].includes(review.status) ? (
                <div className="button-row">
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => assignToMe(review)}
                  >
                    {choose('分配给我', 'Aan mij toewijzen')}
                  </button>
                  <button
                    type="button"
                    className="button button-primary"
                    onClick={() => setSelected(review)}
                  >
                    {choose('处理', 'Afhandelen')}
                  </button>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      ) : null}
      {selected ? (
        <div className="modal-backdrop" role="presentation">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="resolve-title"
          >
            <header className="card-header">
              <div>
                <h2 id="resolve-title">{choose(`处理 ${selected.case_number}`, `Dossier ${selected.case_number} afhandelen`)}</h2>
                <p>{choose(`版本 ${selected.version}。此操作可安全重复提交，并会记录审计日志。`, `Versie ${selected.version}. Deze bewerking is idempotent en wordt gelogd.`)}</p>
              </div>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => {
                  resolutionKey.current = null;
                  setSelected(null);
                }}
              >
                {choose('关闭', 'Sluiten')}
              </button>
            </header>
            <form className="form-stack" onSubmit={resolve}>
              <Field label={choose('处理方式', 'Afhandelwijze')} htmlFor="resolution">
                <select id="resolution" name="resolution" required defaultValue="FULL_REFUND">
                  {RESOLUTIONS.map((value) => (
                    <option
                      key={value}
                      value={value}
                      disabled={
                        !selected.fulfillment_ticket_id &&
                        ['REMAKE', 'SUBSTITUTION'].includes(value)
                      }
                    >
                      {choose(
                        ({ FULL_REFUND: '全额退款', PARTIAL_REFUND: '部分退款', REMAKE: '重新制作', SUBSTITUTION: '替代商品', MANUALLY_FULFILLED: '人工履约完成', NO_FINANCIAL_ACTION: '无需财务操作' } as Record<string, string>)[value] ?? value,
                        ({ FULL_REFUND: 'Volledige terugbetaling', PARTIAL_REFUND: 'Gedeeltelijke terugbetaling', REMAKE: 'Opnieuw bereiden', SUBSTITUTION: 'Vervangend product', MANUALLY_FULFILLED: 'Handmatig uitgevoerd', NO_FINANCIAL_ACTION: 'Geen financiële actie' } as Record<string, string>)[value] ?? value,
                      )}
                    </option>
                  ))}
                </select>
              </Field>
              <Field
                label={choose('部分退款金额（欧元）', 'Bedrag gedeeltelijke terugbetaling (EUR)')}
                htmlFor="refund_amount"
                hint={choose('仅在选择“部分退款”时使用。', 'Alleen gebruiken bij “Gedeeltelijke terugbetaling”.')}
              >
                <input
                  id="refund_amount"
                  name="refund_amount"
                  inputMode="decimal"
                  placeholder="0.00"
                />
              </Field>
              <Field label={choose('备注', 'Notities')} htmlFor="notes">
                <textarea id="notes" name="notes" maxLength={2000} rows={4} />
              </Field>
              <Field
                label={choose('结构化数据', 'Gestructureerde gegevens')}
                htmlFor="payload"
                hint={choose('JSON 对象；用于记录已批准的替代商品或重新制作详情。', 'JSON-object; gebruik dit voor details van een goedgekeurde vervanging of nieuwe bereiding.')}
              >
                <textarea id="payload" name="payload" rows={5} defaultValue="{}" />
              </Field>
              <SubmitButton pending={pending}>{choose('确认处理', 'Afhandeling bevestigen')}</SubmitButton>
            </form>
          </section>
        </div>
      ) : null}
    </section>
  );
}
