import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, FileText, Plus } from 'lucide-react';

import Layout from '../components/Layout';
import KpComparisonTable, { offerTitle } from '../components/kp/KpComparisonTable';
import OfferUpload from '../components/kp/OfferUpload';
import {
  cancelKpRequest, completeKpRequest, confirmKpOfferPrice, createKpOffer, deleteKpOffer,
  deleteKpOfferPrice, getKpRequest, kpErrorText, kpFileDownloadUrl, reopenKpRequest,
  retryKpPricelist, selectKpOffer, setKpOfferPrice, takeKpRequest, updateKpOffer,
} from '../api/kpRequests';
import { refreshKpCounters } from '../hooks/useKpCounters';
import { useAuthStore } from '../stores/auth';
import { KP_INBOX_PATH } from '../utils/roles';
import {
  KP_CATEGORY_LABELS, KP_DEPARTMENT_LABELS, KP_STATUS_LABELS,
  KpOffer, KpOfferForm, KpRequestDetail, KpStatus,
} from '../types/kp';

/**
 * Страница запроса КП — рабочее место отдела производства работ и просмотр
 * для продаж (план plans/2026-09-14-zapros-kp.md, фаза 5, критерии 13–15,
 * 18–22, 28).
 *
 * Все права — из `permissions` ответа сервера, а не из роли на фронте:
 * сотрудник роли загружает КП, вводит и подтверждает цены, пишет отчёт и
 * завершает; продажи смотрят, выбирают КП и возвращают запрос в работу. Поля
 * ввода, на которые у человека нет права, не рисуются вовсе.
 *
 * Страница перечитывается раз в 30 секунд: с запросом одновременно работают
 * все сотрудники роли. После каждого действия — ответ сервера или перечитывание,
 * поэтому 409 («уже завершён», «уже взят») сразу показывает актуальное
 * состояние.
 */

const POLL_MS = 30_000;

const STATUS_COLORS: Record<KpStatus, { bg: string; fg: string }> = {
  new: { bg: '#eff6ff', fg: '#1d4ed8' },
  in_progress: { bg: '#fffbeb', fg: '#b45309' },
  done: { bg: '#f0fdf4', fg: '#15803d' },
  cancelled: { bg: '#f1f5f9', fg: '#64748b' },
};

const SOURCE_LABELS: Record<string, string> = {
  list: 'перечень', completeness: 'полнота', estimate: 'смета', optimization: 'оптимизация',
};

const card: React.CSSProperties = {
  background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 16,
  padding: '16px 20px', boxShadow: '0 4px 24px rgba(0,0,0,0.04)',
};
const sectionTitle: React.CSSProperties = { fontSize: 15, fontWeight: 600, color: '#1e293b', margin: 0 };
const button: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, height: 34, padding: '0 14px',
  borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#475569',
  fontSize: 14, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap',
};
const primary: React.CSSProperties = {
  ...button, border: 'none', background: '#2563eb', color: '#fff', fontWeight: 600,
};

function formatDateTime(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function draftsCount(request: KpRequestDetail): number {
  return request.items.reduce(
    (sum, item) => sum + item.cells.filter((c) => c.price !== null && c.confirmed === false).length, 0,
  );
}

function offerForm(offer: KpOffer): KpOfferForm {
  return {
    supplier_name: offer.supplier_name ?? '',
    offer_date: offer.offer_date ? offer.offer_date.slice(0, 10) : '',
    vat_mode: offer.vat_mode,
    vat_rate: offer.vat_rate !== null ? String(offer.vat_rate) : '22',
    includes_materials: offer.includes_materials,
  };
}

/** Сводка записи в прайс (фаза 7): добавлено / обновлено / пропущено с причинами. */
function PricelistSummary({
  request, canRetry, busy, onRetry,
}: {
  request: KpRequestDetail;
  canRetry: boolean;
  busy: boolean;
  onRetry: () => void;
}) {
  if (request.status !== 'done' || !request.pricelist_status) return null;
  const summary = request.pricelist_summary ?? {};
  const skipped = Object.entries(summary.skipped ?? {}).filter(([, n]) => Number(n) > 0);
  const failed = request.pricelist_status === 'failed';
  return (
    <section style={card} data-testid="kp-pricelist-summary">
      <h2 style={sectionTitle}>Цены в прайсе</h2>
      {failed ? (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
          <div role="alert" style={{
            fontSize: 13, color: '#b91c1c', background: '#fef2f2', border: '1px solid #fecaca',
            borderRadius: 8, padding: '8px 12px',
          }}>
            Цены в прайс не записаны{request.pricelist_error ? `: ${request.pricelist_error}` : ''}.
            Запрос при этом завершён.
          </div>
          {canRetry && (
            <div>
              <button type="button" style={primary} disabled={busy} onClick={onRetry}>
                Записать в прайс ещё раз
              </button>
            </div>
          )}
        </div>
      ) : (
        <div style={{ marginTop: 8, fontSize: 14, color: '#334155', display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div>Добавлено: {Number(summary.added ?? 0)} · Обновлено: {Number(summary.updated ?? 0)}</div>
          {skipped.length > 0 && (
            <div>
              <span style={{ color: '#64748b' }}>Не записано:</span>
              <ul style={{ margin: '4px 0 0', paddingLeft: 20 }}>
                {skipped.map(([reason, n]) => <li key={reason}>{reason} — {Number(n)}</li>)}
              </ul>
            </div>
          )}
          {request.pricelist_written_at && (
            <div style={{ fontSize: 12, color: '#94a3b8' }}>{formatDateTime(request.pricelist_written_at)}</div>
          )}
        </div>
      )}
    </section>
  );
}

const KpRequestPage: React.FC = () => {
  const { requestId = '' } = useParams<{ requestId: string }>();
  const isProduction = useAuthStore((state) => state.isProduction);
  const [request, setRequest] = useState<KpRequestDetail | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [report, setReport] = useState('');
  const [showUpload, setShowUpload] = useState(false);
  const [editingOffer, setEditingOffer] = useState<KpOffer | null>(null);

  const aliveRef = useRef(true);
  const busyRef = useRef(false);
  // Отчёт, который человек уже начал писать, опрос не перетирает.
  const reportTouchedRef = useRef(false);
  const idRef = useRef(requestId);

  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  const accept = useCallback((data: KpRequestDetail) => {
    if (!aliveRef.current || data.id !== idRef.current) return;
    setRequest(data);
    if (!reportTouchedRef.current) setReport(data.report ?? '');
  }, []);

  const reload = useCallback(async (initial = false) => {
    const id = idRef.current;
    try {
      const data = await getKpRequest(id);
      accept(data);
      if (aliveRef.current && id === idRef.current) setLoadError(null);
    } catch (err) {
      // Первая загрузка — ошибка вместо страницы; фоновое перечитывание — молча.
      if (initial && aliveRef.current && id === idRef.current) {
        setLoadError(kpErrorText(err, 'Не удалось открыть запрос КП'));
      }
    }
  }, [accept]);

  useEffect(() => {
    idRef.current = requestId;
    reportTouchedRef.current = false;
    setRequest(null);
    setLoadError(null);
    setError(null);
    setReport('');
    setShowUpload(false);
    setEditingOffer(null);
    reload(true);
    const timer = window.setInterval(() => {
      if (!document.hidden && !busyRef.current) reload();
    }, POLL_MS);
    return () => window.clearInterval(timer);
  }, [requestId, reload]);

  /** Действие с блокировкой кнопок; false — сервер отказал (текст ошибки показан). */
  const run = useCallback(async (action: () => Promise<unknown>, fallback: string): Promise<boolean> => {
    busyRef.current = true;
    setBusy(true);
    setError(null);
    try {
      const result = await action();
      if (result && typeof result === 'object' && 'permissions' in result) {
        accept(result as KpRequestDetail);
      } else {
        await reload();
      }
      return true;
    } catch (err) {
      if (aliveRef.current) setError(kpErrorText(err, fallback));
      // 409 и 404 означают, что состояние изменилось, — показать актуальное.
      await reload();
      return false;
    } finally {
      busyRef.current = false;
      if (aliveRef.current) setBusy(false);
    }
  }, [accept, reload]);

  if (loadError) {
    return (
      <Layout>
        <div style={{ maxWidth: 720, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Link to={isProduction ? KP_INBOX_PATH : '/projects'} style={{ color: '#2563eb', fontSize: 14 }}>
            ← {isProduction ? 'Мои задачи КП' : 'Проекты'}
          </Link>
          <div role="alert" style={{ ...card, color: '#b91c1c' }}>{loadError}</div>
        </div>
      </Layout>
    );
  }

  if (!request) {
    return (
      <Layout>
        <div style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>Загрузка…</div>
      </Layout>
    );
  }

  const perms = request.permissions;
  const category = request.category;
  const status = request.status;
  const colors = STATUS_COLORS[status] ?? STATUS_COLORS.cancelled;
  const drafts = draftsCount(request);
  const canEditOffers = !!perms.can_edit_offers;
  const canComplete = !!perms.can_complete;
  const completeProblems: string[] = [];
  if (!report.trim()) completeProblems.push('Напишите отчёт: кто ответил, сроки поставки, доставка');
  if (drafts > 0) completeProblems.push(`Не подтверждены цены: ${drafts} — подтвердите или исправьте их в таблице`);
  const uploadOpen = canEditOffers && (showUpload || request.offers.length === 0);
  const backTo = isProduction ? KP_INBOX_PATH : `/projects/${request.project_id}/cards/${request.card_id}`;

  const confirmAll = (offerId: string) => run(async () => {
    const itemIds = request.items
      .filter((item) => item.cells.some((c) => c.offer_id === offerId && c.price !== null && c.confirmed === false))
      .map((item) => item.id as string);
    // По одной: сервер подтверждает ячейку, а не КП целиком.
    for (const itemId of itemIds) await confirmKpOfferPrice(offerId, itemId);
  }, 'Не удалось подтвердить цены');

  return (
    <Layout>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16, maxWidth: 1400 }}>
        <Link to={backTo} style={{ color: '#2563eb', fontSize: 14, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
          <ArrowLeft size={14} /> {isProduction ? 'Мои задачи КП' : 'К карточке сметы'}
        </Link>

        <section style={card}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1e293b', margin: 0 }}>
              {KP_CATEGORY_LABELS[category]}
              <span style={{ fontWeight: 400, color: '#64748b' }}> → {KP_DEPARTMENT_LABELS[category]}</span>
            </h1>
            <span style={{
              fontSize: 12, fontWeight: 600, borderRadius: 12, padding: '2px 10px',
              background: colors.bg, color: colors.fg,
            }}>
              {KP_STATUS_LABELS[status] ?? status}
            </span>
            <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 8, flexWrap: 'wrap' }}>
              {status === 'new' && perms.can_work && (
                <button
                  type="button"
                  style={primary}
                  disabled={busy}
                  onClick={async () => {
                    await run(() => takeKpRequest(request.id), 'Не удалось взять запрос в работу');
                    refreshKpCounters();
                  }}
                >
                  Взять в работу
                </button>
              )}
              {perms.can_manage && (status === 'new' || status === 'in_progress') && (
                <button
                  type="button"
                  style={{ ...button, color: '#dc2626' }}
                  disabled={busy}
                  onClick={() => {
                    if (!window.confirm('Отменить запрос КП? Отдел производства перестанет по нему работать.')) return;
                    run(() => cancelKpRequest(request.id), 'Не удалось отменить запрос');
                  }}
                >
                  Отменить
                </button>
              )}
              {perms.can_manage && (status === 'done' || status === 'cancelled') && (
                <button
                  type="button"
                  style={button}
                  disabled={busy}
                  onClick={() => {
                    if (!window.confirm('Вернуть запрос КП в работу отделу производства?')) return;
                    run(() => reopenKpRequest(request.id), 'Не удалось вернуть запрос в работу');
                  }}
                >
                  Вернуть в работу
                </button>
              )}
            </span>
          </div>

          <div style={{
            marginTop: 10, display: 'flex', flexWrap: 'wrap', gap: '4px 20px', fontSize: 14, color: '#334155',
          }}>
            <span>
              <span style={{ color: '#64748b' }}>Объект: </span>
              {[request.project_name, request.card_name].filter(Boolean).join(' · ') || '—'}
            </span>
            <span data-testid="kp-request-author">Автор: {request.author_name ?? '—'}</span>
            <span style={{ color: '#64748b' }}>
              Поставлен {formatDateTime(request.created_at)}
              {SOURCE_LABELS[request.source_kind] ? ` · из стадии «${SOURCE_LABELS[request.source_kind]}»` : ''}
            </span>
            <span>{request.taken_by_name ? `Взял в работу: ${request.taken_by_name}` : 'Никто не взял в работу'}</span>
            {request.completed_by_name && (
              <span>Завершил: {request.completed_by_name} {formatDateTime(request.completed_at)}</span>
            )}
          </div>

          {request.author_comment && (
            <div style={{ marginTop: 10, fontSize: 14 }}>
              <div style={{ color: '#64748b', fontSize: 13 }}>Комментарий автора</div>
              <div style={{ whiteSpace: 'pre-wrap', color: '#1e293b' }}>{request.author_comment}</div>
            </div>
          )}

          <div style={{ marginTop: 10, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 12, fontSize: 14 }}>
            <span style={{ color: '#64748b' }}>Вложения автора:</span>
            {request.files.length === 0 && <span style={{ color: '#94a3b8' }}>нет</span>}
            {request.files.map((file) => (
              <span key={file.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                <FileText size={13} color="#64748b" />
                <a href={kpFileDownloadUrl(file.id)} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>
                  {file.file_name}
                </a>
              </span>
            ))}
          </div>

          {status === 'cancelled' && (
            <div style={{ marginTop: 10, fontSize: 13, color: '#64748b' }}>
              Запрос отменён — работать по нему не нужно.
            </div>
          )}
        </section>

        {error && (
          <div role="alert" style={{
            fontSize: 14, color: '#b91c1c', background: '#fef2f2', border: '1px solid #fecaca',
            borderRadius: 8, padding: '8px 12px',
          }}>
            {error}
          </div>
        )}

        <section style={{ ...card, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <h2 style={sectionTitle}>Позиции и КП</h2>
            <span style={{ fontSize: 13, color: '#94a3b8' }}>
              позиций: {request.items.length} · КП: {request.offers.length}
            </span>
            {canEditOffers && !uploadOpen && !editingOffer && (
              <button type="button" style={{ ...button, marginLeft: 'auto' }} disabled={busy} onClick={() => setShowUpload(true)}>
                <Plus size={14} /> Добавить КП
              </button>
            )}
          </div>

          {uploadOpen && !editingOffer && (
            <OfferUpload
              category={category}
              busy={busy}
              onCancel={request.offers.length > 0 ? () => setShowUpload(false) : undefined}
              onSubmit={async (form, file) => {
                const ok = await run(
                  () => createKpOffer(request.id, form, file, category), 'Не удалось загрузить КП',
                );
                if (ok) {
                  setShowUpload(false);
                  // Загрузка КП в новый запрос берёт его в работу — счётчик новых меняется.
                  refreshKpCounters();
                }
                return ok;
              }}
            />
          )}

          {editingOffer && canEditOffers && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <span style={{ fontSize: 13, color: '#64748b' }}>Условия КП «{offerTitle(editingOffer)}»</span>
              <OfferUpload
                key={editingOffer.id}
                mode="edit"
                category={category}
                hasFile={editingOffer.has_file}
                initial={offerForm(editingOffer)}
                busy={busy}
                onCancel={() => setEditingOffer(null)}
                onSubmit={async (form) => {
                  const ok = await run(
                    () => updateKpOffer(editingOffer.id, form, category), 'Не удалось сохранить условия КП',
                  );
                  if (ok) setEditingOffer(null);
                  return ok;
                }}
              />
            </div>
          )}

          <KpComparisonTable
            request={request}
            busy={busy}
            onSetPrice={(offerId, itemId, body) => run(
              () => setKpOfferPrice(offerId, itemId, body), 'Не удалось сохранить цену',
            )}
            onConfirm={(offerId, itemId) => run(
              () => confirmKpOfferPrice(offerId, itemId), 'Не удалось подтвердить цену',
            )}
            onConfirmAll={confirmAll}
            onDeletePrice={(offerId, itemId) => run(
              () => deleteKpOfferPrice(offerId, itemId), 'Не удалось удалить цену',
            )}
            onSelect={(itemId, offerId) => run(
              () => selectKpOffer(itemId, offerId), 'Не удалось сохранить выбор КП',
            )}
            onEditOffer={(offer) => { setShowUpload(false); setEditingOffer(offer); }}
            onDeleteOffer={async (offer) => {
              if (!window.confirm(`Удалить КП «${offerTitle(offer)}» вместе с его ценами?`)) return false;
              const ok = await run(() => deleteKpOffer(offer.id), 'Не удалось удалить КП');
              if (ok && editingOffer?.id === offer.id) setEditingOffer(null);
              return ok;
            }}
          />
        </section>

        {canComplete ? (
          <section style={{ ...card, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <label htmlFor="kp-report" style={sectionTitle}>Отчёт</label>
            <textarea
              id="kp-report"
              value={report}
              maxLength={20000}
              disabled={busy}
              onChange={(e) => {
                reportTouchedRef.current = true;
                setReport(e.target.value);
              }}
              placeholder="Кто ответил, сроки поставки, доставка, минимальная партия"
              rows={4}
              style={{
                width: '100%', boxSizing: 'border-box', padding: '8px 10px', borderRadius: 8,
                border: '1px solid #e2e8f0', fontSize: 14, fontFamily: 'inherit', resize: 'vertical',
              }}
            />
            {completeProblems.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2, fontSize: 13, color: '#b45309' }}>
                {completeProblems.map((text) => <span key={text}>{text}</span>)}
              </div>
            )}
            <div>
              <button
                type="button"
                style={{ ...primary, background: busy || completeProblems.length > 0 ? '#93c5fd' : '#2563eb' }}
                disabled={busy || completeProblems.length > 0}
                onClick={async () => {
                  const ok = await run(
                    () => completeKpRequest(request.id, report.trim()), 'Не удалось завершить запрос',
                  );
                  if (ok) {
                    reportTouchedRef.current = false;
                    refreshKpCounters();
                  }
                }}
              >
                Завершить
              </button>
            </div>
          </section>
        ) : request.report ? (
          <section style={card}>
            <h2 style={sectionTitle}>Отчёт</h2>
            <div style={{ marginTop: 8, whiteSpace: 'pre-wrap', fontSize: 14, color: '#1e293b' }}>{request.report}</div>
          </section>
        ) : null}

        <PricelistSummary
          request={request}
          canRetry={perms.can_work || perms.can_manage}
          busy={busy}
          onRetry={() => { run(() => retryKpPricelist(request.id), 'Не удалось записать цены в прайс'); }}
        />
      </div>
    </Layout>
  );
};

export default KpRequestPage;
