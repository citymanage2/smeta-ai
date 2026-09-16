import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Check, X } from 'lucide-react';

import { applyKpPrices, kpErrorText, previewKpApply } from '../../api/kpRequests';
import { formatDecimal, formatMoney } from '../../utils/formatNumber';
import { formatFactor, isActiveCoefficient } from '../../utils/estimateCalc';
import { toNumber } from '../editor/adapters/types';
import { LumaSpin } from '../ui/LumaSpin';
import type { KpApplyItem, KpApplyPreview, KpApplyResult } from '../../types/kp';

/**
 * Предпросмотр и применение цен из КП к оптимизации
 * (план plans/2026-09-14-zapros-kp.md, фаза 8; критерии 31–37 спецификации).
 *
 * Окно ничего не считает само: какие строки получат цену, какие позиции не
 * нашлись и какие неоднозначны — решает сервер. Человек только выбирает строку
 * для «Неоднозначно» (или пропускает позицию). «Применить» отправляет `rev` и
 * хэш именно этого предпросмотра: если коллега успел поправить оптимизацию,
 * сервер ответит 409, ничего не запишет — и нужен новый предпросмотр.
 */

interface Props {
  cardId: string;
  /** Последняя неоткатанная версия оптимизации — к ней и применяются цены. */
  versionId: string;
  /**
   * Коэффициент к ценам версии (`{work, material, scope}`), если известен.
   * Новая версия его наследует, и в таблице цены КП покажутся умноженными —
   * без пояснения «Стало 100» и «в таблице 120» выглядят как ошибка.
   */
  coefficient?: unknown;
  onClose: () => void;
  onApplied: (result: KpApplyResult) => void;
  /**
   * Перечитать версии документа. Предпросмотр ответил 409 — цены применяются к
   * последней версии, а редактор знает устаревший список.
   */
  onRefreshDocument?: () => Promise<void>;
}

const SKIP = '';

const overlayStyle: React.CSSProperties = {
  position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(15,23,42,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
};

const modalStyle: React.CSSProperties = {
  background: '#fff', borderRadius: 16, width: 'min(920px, 100%)',
  maxHeight: '88vh', display: 'flex', flexDirection: 'column', overflow: 'hidden',
  boxShadow: '0 20px 60px rgba(15,23,42,0.25)', color: '#1e293b',
};

const buttonStyle: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 6, height: 32, padding: '0 14px',
  borderRadius: 8, border: '1px solid #e2e8f0', background: '#fff', color: '#475569',
  fontSize: 13, fontWeight: 500, cursor: 'pointer',
};

function primaryStyle(disabled: boolean): React.CSSProperties {
  return {
    ...buttonStyle,
    border: `1px solid ${disabled ? '#e2e8f0' : '#2563eb'}`,
    background: disabled ? '#e2e8f0' : '#2563eb',
    color: disabled ? '#94a3b8' : '#fff',
    fontWeight: 600,
    cursor: disabled ? 'not-allowed' : 'pointer',
  };
}

const noteStyle = (tone: 'warn' | 'info' | 'error'): React.CSSProperties => ({
  display: 'flex', gap: 8, alignItems: 'flex-start', fontSize: 13, lineHeight: 1.45,
  padding: '8px 12px', borderRadius: 8,
  background: tone === 'warn' ? '#fffbeb' : tone === 'error' ? '#fef2f2' : '#f8fafc',
  border: `1px solid ${tone === 'warn' ? '#fcd34d' : tone === 'error' ? '#fecaca' : '#e2e8f0'}`,
  color: tone === 'warn' ? '#92400e' : tone === 'error' ? '#b91c1c' : '#475569',
});

const cellStyle: React.CSSProperties = {
  padding: '6px 8px', borderBottom: '1px solid #f1f5f9', verticalAlign: 'top', fontSize: 13,
};

const headStyle: React.CSSProperties = {
  ...cellStyle, fontWeight: 600, color: '#64748b', fontSize: 12, textAlign: 'left',
  borderBottom: '1px solid #e2e8f0', background: '#f8fafc',
};

/** Цена сервера — число или строка; пусто — прочерк. */
function money(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const num = typeof value === 'number' ? value : Number(String(value).replace(',', '.'));
  return Number.isFinite(num) ? formatMoney(num) : String(value);
}

/** «2026-09-10» → «10.09.2026». */
export function formatKpDate(value: string | null | undefined): string {
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value ?? ''));
  return iso ? `${iso[3]}.${iso[2]}.${iso[1]}` : '';
}

/** «ООО Кирпич от 10.09.2026 · КП: 3». */
function offerLabel(item: {
  supplier: string | null; offer_date: string | null; offers_count: number;
}): string {
  const date = formatKpDate(item.offer_date);
  return `${item.supplier || 'поставщик не указан'}${date ? ` от ${date}` : ''} · КП: ${item.offers_count}`;
}

function conflictText(error: unknown): string {
  const status = (error as { response?: { status?: number } })?.response?.status;
  if (status === 409) {
    return 'Оптимизацию успели изменить (коллега применил правки или появилась новая версия) — '
      + 'ничего не записано. Обновите предпросмотр и примените заново.';
  }
  if (status === 403) return 'Применять цены из КП к оптимизации может только отдел продаж.';
  return kpErrorText(error, 'Не удалось применить цены из КП');
}

/** Позиция «Неоднозначно»: выбор одной строки из кандидатов или пропуск. */
const AmbiguousItem: React.FC<{
  item: KpApplyItem;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}> = ({ item, value, disabled, onChange }) => {
  const group = `kp-ambiguous-${item.item_id}`;
  return (
    <div style={{ padding: '8px 0', borderBottom: '1px solid #fef3c7', fontSize: 13 }}>
      <div>
        <b>{item.name}</b>{item.unit ? `, ${item.unit}` : ''} — {money(item.price)}
        <span style={{ color: '#64748b' }}> · {offerLabel(item)}</span>
        {item.includes_materials && (
          <span style={{ color: '#c2410c' }}> · включает материалы</span>
        )}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, marginTop: 4 }}>
        {item.candidates.map((c) => (
          <label key={c.row_id} style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer' }}>
            <input
              type="radio" name={group} value={c.row_id}
              checked={value === c.row_id} disabled={disabled}
              onChange={() => onChange(c.row_id)}
            />
            <span>
              {c.source_no ? `№ ${c.source_no} · ` : ''}{c.name}{c.unit ? `, ${c.unit}` : ''}
              {c.sheet ? ` · ${c.sheet}` : ''}
              {c.qty !== null && c.qty !== undefined && c.qty !== ''
                ? ` · объём ${Number.isFinite(Number(c.qty)) ? formatDecimal(Number(c.qty)) : String(c.qty)}`
                : ''}
              {` · ${money(c.old_price)} → ${money(c.new_price)}`}
            </span>
          </label>
        ))}
        <label style={{ display: 'flex', gap: 6, alignItems: 'center', cursor: 'pointer', color: '#64748b' }}>
          <input
            type="radio" name={group} value={SKIP}
            checked={value === SKIP} disabled={disabled}
            onChange={() => onChange(SKIP)}
          />
          Пропустить позицию
        </label>
      </div>
    </div>
  );
};

/** «В таблице цены покажутся с коэффициентом ×1,2» — или null, если коэффициента нет. */
export function coefficientNote(coefficient: unknown): string | null {
  if (!isActiveCoefficient(coefficient)) return null;
  const value = coefficient as Record<string, unknown>;
  const work = toNumber(value.work) ?? 1;
  const material = toNumber(value.material) ?? 1;
  const factor = (raw: number) => (raw > 0 ? raw : 1);
  const w = factor(work);
  const m = factor(material);
  if (w === 1 && m === 1) return null;
  const partial = Array.isArray(value.scope) ? ' (у выбранных строк)' : '';
  const text = w === m
    ? `×${formatFactor(w)}`
    : `работ ×${formatFactor(w)}, материалов ×${formatFactor(m)}`;
  return `В таблице цены покажутся с коэффициентом ${text}${partial}: `
    + 'здесь — цены КП без коэффициента, как они запишутся в версию.';
}

const KpApplyDialog: React.FC<Props> = ({
  cardId, versionId, coefficient, onClose, onApplied, onRefreshDocument,
}) => {
  const [data, setData] = useState<KpApplyPreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [loadConflict, setLoadConflict] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // Версия читается из ref: после «Обновить документ» новая версия приходит
  // пропсом, и предпросмотр должен взять её, а не ту, что была в замыкании.
  const versionRef = useRef(versionId);
  versionRef.current = versionId;
  // Ответ устаревшего предпросмотра не должен перетереть свежий.
  const loadSeqRef = useRef(0);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);

  const load = useCallback(async () => {
    const seq = ++loadSeqRef.current;
    setData(null);
    setLoadError(null);
    setLoadConflict(false);
    setApplyError(null);
    setStale(false);
    setChoices({});
    try {
      const preview = await previewKpApply(cardId, versionRef.current);
      if (seq === loadSeqRef.current) setData(preview);
    } catch (error) {
      if (seq !== loadSeqRef.current) return;
      const status = (error as { response?: { status?: number } })?.response?.status;
      setLoadConflict(status === 409);
      setLoadError(status === 409
        ? kpErrorText(error, 'Цены из КП применяются к последней версии оптимизации — обновите документ и повторите')
        : kpErrorText(error, 'Не удалось собрать предпросмотр цен из КП'));
    }
  }, [cardId]);

  const handleRefreshDocument = useCallback(async () => {
    if (!onRefreshDocument) return;
    setRefreshing(true);
    try {
      await onRefreshDocument();
    } catch {
      // Не удалось перечитать — предпросмотр ниже скажет, что не так.
    } finally {
      setRefreshing(false);
    }
    await load();
  }, [onRefreshDocument, load]);

  const note = coefficientNote(coefficient);

  useEffect(() => { void load(); }, [load, versionId]);

  const chosenCount = useMemo(
    () => Object.values(choices).filter((value) => value !== SKIP).length,
    [choices],
  );
  const nothing = !!data && data.rows.length === 0 && chosenCount === 0;
  const applyDisabled = !data || applying || stale || nothing;

  const handleApply = useCallback(async () => {
    if (!data) return;
    setApplying(true);
    setApplyError(null);
    // По каждой неоднозначной позиции — выбор человека; не выбрал — пропуск
    // (null), а не «первая попавшаяся строка».
    const body: Record<string, string | null> = {};
    for (const item of data.ambiguous) {
      const picked = choices[item.item_id];
      body[item.item_id] = picked ? picked : null;
    }
    try {
      const result = await applyKpPrices({
        card_id: cardId, version_id: data.version_id, client_rev: data.rev,
        preview_hash: data.preview_hash, choices: body,
      });
      onApplied(result);
    } catch (error) {
      const status = (error as { response?: { status?: number } })?.response?.status;
      if (status === 409) setStale(true);
      setApplyError(conflictText(error));
    } finally {
      setApplying(false);
    }
  }, [data, choices, cardId, onApplied]);

  return (
    <div style={overlayStyle} role="dialog" aria-modal="true" aria-label="Цены из КП">
      <div style={modalStyle}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 18px', borderBottom: '1px solid #e2e8f0',
        }}>
          <b style={{ fontSize: 15 }}>Цены из КП в оптимизацию</b>
          <button
            type="button" style={{ ...buttonStyle, border: 'none', padding: '0 6px' }}
            onClick={onClose} disabled={applying} aria-label="Закрыть"
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ overflowY: 'auto', padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {!data && !loadError && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, color: '#64748b' }}>
              <LumaSpin size="sm" color="#3b82f6" /> Сопоставляю позиции КП со строками оптимизации…
            </div>
          )}
          {loadError && <div style={noteStyle('error')} role="alert">{loadError}</div>}
          {loadConflict && onRefreshDocument && (
            <div>
              <button
                type="button" style={buttonStyle} disabled={refreshing}
                onClick={() => void handleRefreshDocument()}
              >
                Обновить документ
              </button>
            </div>
          )}

          {data && (
            <>
              <div style={noteStyle('info')}>
                Будет создана новая версия оптимизации «Цены из КП». Текущая версия не
                меняется — новую можно откатить, как любую другую.
              </div>
              {note && (
                <div data-testid="kp-apply-coefficient" style={noteStyle('warn')}>{note}</div>
              )}

              {nothing && (
                <div data-testid="kp-apply-nothing" style={noteStyle('warn')}>
                  <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: 1 }} />
                  <span>
                    Нет строк, которым можно поставить цену из КП
                    {data.ambiguous.length > 0 ? ' — выберите строку для неоднозначных позиций ниже' : ''}.
                  </span>
                </div>
              )}

              {data.rows.length > 0 && (
                <section>
                  <b style={{ fontSize: 14 }}>Получат цену из КП: {data.rows.length}</b>
                  <div style={{ overflowX: 'auto', marginTop: 6 }}>
                    <table data-testid="kp-apply-rows" style={{ borderCollapse: 'collapse', width: '100%' }}>
                      <thead>
                        <tr>
                          <th style={headStyle}>№</th>
                          <th style={headStyle}>Наименование</th>
                          <th style={headStyle}>Ед.</th>
                          <th style={{ ...headStyle, textAlign: 'right' }}>Было</th>
                          <th style={{ ...headStyle, textAlign: 'right' }}>Стало</th>
                          <th style={headStyle}>КП</th>
                        </tr>
                      </thead>
                      <tbody>
                        {data.rows.map((r) => (
                          <tr
                            key={`${r.row_id}:${r.field}`}
                            data-testid={`kp-apply-row-${r.row_id}`}
                            style={{ background: r.includes_materials ? '#fce4d6' : undefined }}
                          >
                            <td style={cellStyle}>{r.source_no ?? ''}</td>
                            <td style={cellStyle}>
                              {r.name}
                              {r.sheet && <span style={{ color: '#94a3b8' }}> · {r.sheet}</span>}
                              <div style={{ color: '#94a3b8', fontSize: 12 }}>
                                {r.field === 'price_work' ? 'цена работы' : 'цена материала'}
                              </div>
                            </td>
                            <td style={cellStyle}>{r.unit ?? ''}</td>
                            <td style={{ ...cellStyle, textAlign: 'right', color: '#64748b' }}>{money(r.old_price)}</td>
                            <td style={{ ...cellStyle, textAlign: 'right', fontWeight: 600 }}>{money(r.new_price)}</td>
                            <td style={cellStyle}>
                              {offerLabel(r)}
                              {r.includes_materials && (
                                <div style={{ color: '#c2410c', fontSize: 12 }}>
                                  включает материалы — проверьте материал позиции
                                </div>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )}

              {data.includes_materials_count > 0 && (
                <div data-testid="kp-apply-includes-materials" style={noteStyle('warn')}>
                  Цены работ, которые включают материалы: {data.includes_materials_count}.
                  Цена материала у таких строк не меняется — проверьте её сами.
                </div>
              )}

              {data.ambiguous.length > 0 && (
                <section data-testid="kp-apply-ambiguous" style={{
                  border: '1px solid #fcd34d', borderRadius: 12, padding: '10px 14px', background: '#fffdf5',
                }}>
                  <b style={{ fontSize: 14 }}>Неоднозначно: {data.ambiguous.length}</b>
                  <div style={{ fontSize: 12, color: '#92400e', marginTop: 2 }}>
                    Позиции КП подходят к нескольким строкам. Выберите строку — или пропустите позицию.
                  </div>
                  {data.ambiguous.map((item) => (
                    <AmbiguousItem
                      key={item.item_id}
                      item={item}
                      value={choices[item.item_id] ?? SKIP}
                      disabled={applying}
                      onChange={(value) => setChoices((prev) => ({ ...prev, [item.item_id]: value }))}
                    />
                  ))}
                </section>
              )}

              {data.not_found.length > 0 && (
                <section data-testid="kp-apply-not-found">
                  <b style={{ fontSize: 14 }}>Не найдено в оптимизации: {data.not_found.length}</b>
                  <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>
                    Строки с таким наименованием и типом нет — цена не применится.
                  </div>
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 13 }}>
                    {data.not_found.map((item) => (
                      <li key={item.item_id}>
                        {item.name}{item.unit ? `, ${item.unit}` : ''} — {money(item.price)} ({offerLabel(item)})
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              {data.skipped.length > 0 && (
                <section data-testid="kp-apply-skipped">
                  <b style={{ fontSize: 14 }}>Пропущено: {data.skipped.length}</b>
                  <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 13 }}>
                    {data.skipped.map((s) => (
                      <li key={`${s.item_id}:${s.row_id}`}>{s.name ?? ''} — {s.reason}</li>
                    ))}
                  </ul>
                </section>
              )}

              {data.no_price_count > 0 && (
                <div style={noteStyle('info')}>
                  Позиций без подтверждённой цены в КП: {data.no_price_count} — они не применяются.
                </div>
              )}
            </>
          )}

          {applyError && <div style={noteStyle('error')} role="alert">{applyError}</div>}
        </div>

        <div style={{
          padding: '12px 18px', borderTop: '1px solid #e2e8f0',
          display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        }}>
          <span style={{ fontSize: 12, color: '#64748b', flex: 1, minWidth: 200 }}>
            {data && !nothing && `Строк с новой ценой: ${data.rows.length}`
              + (chosenCount > 0 ? ` и выбранных вручную: ${chosenCount}` : '')}
          </span>
          {stale && (
            <button type="button" style={buttonStyle} onClick={() => void load()} disabled={applying}>
              Обновить предпросмотр
            </button>
          )}
          <button type="button" style={buttonStyle} onClick={onClose} disabled={applying}>
            Отмена
          </button>
          <button
            type="button"
            style={primaryStyle(applyDisabled)}
            onClick={handleApply}
            disabled={applyDisabled}
          >
            {applying ? <LumaSpin size="sm" color="#94a3b8" /> : <Check size={14} />}
            Применить
          </button>
        </div>
      </div>
    </div>
  );
};

export default KpApplyDialog;
