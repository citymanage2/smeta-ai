import React, { useCallback, useMemo, useRef, useState } from 'react';

import {
  ReferenceDuplicate,
  ReferencePreview,
  referenceApply,
  referencePreview,
} from '../../api/catalog';
import { formatApiDetail } from '../../utils/formatError';

/**
 * «Эталон» — загрузить файл, цены из которого становятся единственно верными.
 *
 * План `plans/2026-09-02-etalonnyy-prays-iz-smety.md`.
 *
 * Отличие от соседней кнопки «Импорт» — в направлении: та **добавляет** цену к
 * уже имеющимся, эта **убирает** остальные. Операция необратима и трогает общий
 * на всех прайс, поэтому она разбита на два шага: сначала человек видит, какие
 * именно цены исчезнут и какие позиции система считает тем же самым под другим
 * названием, и только потом жмёт «Применить».
 *
 * Галочки на дублях по умолчанию сняты: система показывает догадку, а удаляет
 * человек.
 */

interface Props {
  /** Тип позиций для простого прайса «Наименование / Ед. / Цена». В файле
   *  сметы тип написан в самой таблице, и этот выбор не используется. */
  kind: 'work' | 'material';
  onDone: () => void;
}

function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Ключ строки-кандидата: источник и id, как их ждёт сервер. */
export function duplicateKey(candidate: ReferenceDuplicate): string {
  return `${candidate.source}:${candidate.kind}:${candidate.id}`;
}

const ReferenceImport: React.FC<Props> = ({ kind, onDone }) => {
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<ReferencePreview | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState('');

  const handleFile = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setLoading(true);
    setError('');
    try {
      const result = await referencePreview(file, kind);
      setPreview(result);
      setChecked(new Set());
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(formatApiDetail(detail, 'Не удалось разобрать файл. Проверьте его структуру.'));
    } finally {
      setLoading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }, [kind]);

  const toggle = useCallback((key: string) => {
    setChecked(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const handleApply = useCallback(async () => {
    if (!preview) return;
    setApplying(true);
    setError('');
    try {
      const remove = preview.duplicates.candidates
        .filter(c => checked.has(duplicateKey(c)))
        .map(c => ({ source: c.source, kind: c.kind, id: c.id }));
      await referenceApply(preview.items, remove);
      setPreview(null);
      setChecked(new Set());
      onDone();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(formatApiDetail(detail, 'Не удалось применить цены. Попробуйте ещё раз.'));
    } finally {
      setApplying(false);
    }
  }, [preview, checked, onDone]);

  const erased = useMemo(
    () => (preview?.plan ?? []).filter(entry => entry.removed.length > 0),
    [preview],
  );
  const blocked = useMemo(
    () => (preview?.plan ?? []).filter(entry => entry.action === 'blocked'),
    [preview],
  );

  return (
    <>
      <button
        style={{ ...st.btn, opacity: loading ? 0.7 : 1 }}
        onClick={() => fileRef.current?.click()}
        disabled={loading}
        title="Цены из файла станут единственными: другие цены по этим позициям будут стёрты"
      >
        {loading ? 'Читаю файл...' : '↑ Эталон'}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".xlsx,.xls,.csv,.txt"
        style={{ display: 'none' }}
        onChange={handleFile}
        data-testid="reference-file"
      />

      {error && !preview && <div style={st.errorToast}>{error}</div>}

      {preview && (
        <div style={st.overlay} onClick={e => { if (e.target === e.currentTarget) setPreview(null); }}>
          <div style={st.modal}>
            <div style={st.title}>Эталонные цены из файла</div>

            {error && <div style={st.error}>{error}</div>}

            <div style={st.summary}>
              <span><b>{preview.summary.add ?? 0}</b> добавится</span>
              <span><b>{preview.summary.reprice ?? 0}</b> заменит цены</span>
              {(preview.summary.blocked ?? 0) > 0 && (
                <span style={{ color: '#b45309' }}><b>{preview.summary.blocked}</b> пропущено по ед. изм.</span>
              )}
              {Object.entries(preview.notes ?? {}).map(([note, count]) => (
                <span key={note} style={{ color: '#b45309' }}>
                  <b>{count}</b> {note}
                </span>
              ))}
              {(preview.summary.skipped ?? 0) > 0 && (
                <span style={{ color: '#64748b' }}>
                  <b>{preview.summary.skipped}</b> строк не взято
                  {Object.keys(preview.skipped).length > 0 && (
                    <> ({Object.entries(preview.skipped).map(([r, n]) => `${r} — ${n}`).join(', ')})</>
                  )}
                </span>
              )}
            </div>

            {erased.length > 0 && (
              <div style={st.block}>
                <div style={st.blockTitle}>Эти цены будут стёрты</div>
                <table style={st.table}>
                  <thead>
                    <tr>
                      <th style={st.th}>Позиция</th>
                      <th style={st.th}>Станет</th>
                      <th style={st.th}>Исчезнет</th>
                    </tr>
                  </thead>
                  <tbody>
                    {erased.map(entry => (
                      <tr key={`${entry.kind}:${entry.name}`}>
                        <td style={st.td}>
                          {entry.name}
                          <span style={st.muted}> · {entry.unit || '—'}</span>
                        </td>
                        <td style={st.td}>{money(entry.price)}</td>
                        <td style={{ ...st.td, color: '#b91c1c' }}>
                          {entry.removed
                            .map(r => (r.contractor ? `${r.contractor}: ${money(r.price)}` : money(r.price)))
                            .join(', ')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {preview.conflicts.length > 0 && (
              <div style={st.block}>
                <div style={st.blockTitle}>
                  В файле разные цены у одной позиции — проверьте, какая верна
                </div>
                <div style={st.note}>
                  Записана будет последняя из встреченных. Если верна другая — поправьте
                  файл или позицию в каталоге после загрузки.
                </div>
                <table style={st.table}>
                  <thead>
                    <tr>
                      <th style={st.th}>Позиция</th>
                      <th style={st.th}>Цены в файле</th>
                      <th style={st.th}>Будет записана</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.conflicts.map(conflict => (
                      <tr key={`c:${conflict.kind}:${conflict.name}`}>
                        <td style={st.td}>
                          {conflict.name}
                          <span style={st.muted}> · {conflict.unit || '—'}</span>
                        </td>
                        <td style={st.td}>{conflict.prices.map(money).join(' / ')}</td>
                        <td style={{ ...st.td, fontWeight: 600 }}>{money(conflict.taken)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {blocked.length > 0 && (
              <div style={st.block}>
                <div style={st.blockTitle}>Не тронем — единица измерения не сводится</div>
                <div style={st.note}>
                  Цена в прайсе назначена за другую величину, и подменять её ценой из файла
                  нельзя. Проверьте позиции вручную:
                </div>
                <ul style={st.list}>
                  {blocked.map(entry => (
                    <li key={`b:${entry.kind}:${entry.name}`} style={st.li}>
                      {entry.name} — в файле <b>{entry.unit || '—'}</b>, в прайсе{' '}
                      <b>{entry.match?.unit || '—'}</b>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div style={st.block}>
              <div style={st.blockTitle}>
                Похожие позиции — возможно, то же самое под другим названием
              </div>
              {!preview.duplicates.vectors_ready ? (
                <div style={st.warn}>
                  Поиск по смыслу отключён — у прайса нет векторов. Работает только точное
                  совпадение названия, поэтому список пуст не потому, что дублей нет.
                  Сгенерируйте векторы в админке.
                </div>
              ) : preview.duplicates.candidates.length === 0 ? (
                <div style={st.note}>Похожих позиций не нашлось.</div>
              ) : (
                <>
                  <div style={st.note}>
                    Отмеченные будут удалены из прайса и кеша. По умолчанию не отмечено ничего.
                  </div>
                  <table style={st.table}>
                    <thead>
                      <tr>
                        <th style={st.th}> </th>
                        <th style={st.th}>Позиция в базе</th>
                        <th style={st.th}>Цена</th>
                        <th style={st.th}>Где</th>
                        <th style={st.th}>Похоже на</th>
                      </tr>
                    </thead>
                    <tbody>
                      {preview.duplicates.candidates.map(candidate => {
                        const key = duplicateKey(candidate);
                        return (
                          <tr key={key}>
                            <td style={st.td}>
                              <input
                                type="checkbox"
                                aria-label={`Удалить ${candidate.name}`}
                                checked={checked.has(key)}
                                onChange={() => toggle(key)}
                              />
                            </td>
                            <td style={st.td}>
                              {candidate.name}
                              <span style={st.muted}> · {candidate.unit || '—'}</span>
                            </td>
                            <td style={st.td}>{money(candidate.price)}</td>
                            <td style={st.td}>
                              {candidate.source === 'cache' ? 'кеш веб-поиска' : 'прайс'}
                            </td>
                            <td style={{ ...st.td, color: '#64748b' }}>
                              {candidate.for_name} ({Math.round(candidate.score * 100)}%)
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </>
              )}
            </div>

            <div style={st.footer}>
              <button style={st.btn} onClick={() => setPreview(null)} disabled={applying}>
                Отмена
              </button>
              <button
                style={{ ...st.btn, ...st.btnPrimary, opacity: applying ? 0.7 : 1 }}
                onClick={handleApply}
                disabled={applying}
              >
                {applying ? 'Применяю...' : `Применить${checked.size > 0 ? ` и удалить ${checked.size}` : ''}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

const st = {
  btn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    padding: '7px 14px',
    borderRadius: 6,
    fontSize: 13,
    fontWeight: 500,
    cursor: 'pointer',
    border: '1px solid #e2e8f0',
    background: '#fff',
    color: '#374151',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,

  btnPrimary: {
    background: '#2563eb',
    color: '#fff',
    border: '1px solid #2563eb',
  } as React.CSSProperties,

  overlay: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(15,23,42,0.35)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  } as React.CSSProperties,

  modal: {
    background: '#fff',
    borderRadius: 10,
    padding: '24px 28px',
    width: '100%',
    maxWidth: 880,
    maxHeight: '90vh',
    overflowY: 'auto' as const,
    boxShadow: '0 8px 32px rgba(0,0,0,0.18)',
  } as React.CSSProperties,

  title: {
    fontSize: 17,
    fontWeight: 700,
    color: '#1e293b',
    marginBottom: 14,
  } as React.CSSProperties,

  summary: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: 16,
    fontSize: 13,
    color: '#334155',
    marginBottom: 18,
  } as React.CSSProperties,

  block: {
    marginBottom: 20,
  } as React.CSSProperties,

  blockTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: '#475569',
    marginBottom: 8,
  } as React.CSSProperties,

  note: {
    fontSize: 12,
    color: '#64748b',
    marginBottom: 8,
    lineHeight: 1.5,
  } as React.CSSProperties,

  warn: {
    padding: '10px 12px',
    background: '#fffbeb',
    border: '1px solid #fde68a',
    borderRadius: 6,
    fontSize: 12,
    color: '#92400e',
    lineHeight: 1.5,
  } as React.CSSProperties,

  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 13,
  } as React.CSSProperties,

  th: {
    textAlign: 'left' as const,
    padding: '6px 8px',
    borderBottom: '1px solid #e2e8f0',
    fontSize: 12,
    fontWeight: 600,
    color: '#64748b',
  } as React.CSSProperties,

  td: {
    padding: '6px 8px',
    borderBottom: '1px solid #f1f5f9',
    color: '#1e293b',
    verticalAlign: 'top' as const,
  } as React.CSSProperties,

  muted: {
    color: '#94a3b8',
  } as React.CSSProperties,

  list: {
    margin: 0,
    paddingLeft: 18,
  } as React.CSSProperties,

  li: {
    fontSize: 13,
    color: '#1e293b',
    marginBottom: 4,
  } as React.CSSProperties,

  error: {
    padding: '10px 14px',
    background: '#fef2f2',
    color: '#b91c1c',
    borderRadius: 6,
    fontSize: 13,
    marginBottom: 14,
  } as React.CSSProperties,

  errorToast: {
    padding: '8px 12px',
    background: '#fef2f2',
    color: '#b91c1c',
    borderRadius: 6,
    fontSize: 12,
  } as React.CSSProperties,

  footer: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 10,
    marginTop: 8,
  } as React.CSSProperties,
};

export default ReferenceImport;
