import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AlertTriangle, Paperclip, Send, X } from 'lucide-react';

import {
  checkKpAttachments, createKpRequests, kpErrorText, previewKpRequest,
} from '../../api/kpRequests';
import { ROLE_LABELS } from '../../api/adminUsers';
import { formatDecimal } from '../../utils/formatNumber';
import { LumaSpin } from '../ui/LumaSpin';
import {
  KP_CATEGORY_LABELS, KP_DEPARTMENT_LABELS, KP_MAX_FILES,
  KpCategory, KpItem, KpPreview, KpRequestBrief, KpSourceKind,
} from '../../types/kp';

/**
 * Окно «Запросить КП» (план plans/2026-09-14-zapros-kp.md, фаза 3).
 *
 * Как устроено и почему:
 * * **Разбивку делает сервер.** Предпросмотр перечитывает сохранённый документ
 *   и сворачивает одинаковые позиции тем же ключом, что свёртка дублей на
 *   экране. Окно ничего не пересчитывает: отправляются ровно те строки, что
 *   сервер показал в группах (`source_row_ids`), — строки, которых в
 *   применённом документе нет, в запрос не уходят и названы числом.
 * * **Запрос адресован роли.** Нет ни одного активного сотрудника роли — группа
 *   показана с причиной и не отправляется; сервер проверяет то же (422).
 * * **Позицию без типа относит человек.** Молча отправить её снабженцам или
 *   подрядчикам окно не вправе, поэтому «Отправить» ждёт явного выбора —
 *   в том числе «Не запрашивать».
 */

interface Props {
  cardId: string;
  kind: KpSourceKind;
  /** Открытая версия документа; null — рабочая. */
  versionId: string | null;
  /** Ключи отмеченных строк документа (свёрнутая группа — все её строки). */
  rowIds: string[];
  /** В таблице есть непринятые правки — в запрос они не попадут. */
  isDirty: boolean;
  onClose: () => void;
  onCreated: (requests: KpRequestBrief[]) => void;
}

type Decision = KpCategory | 'skip';

const CATEGORIES: KpCategory[] = ['material', 'work'];

const overlayStyle: React.CSSProperties = {
  position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(15,23,42,0.45)',
  display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 16,
};

const modalStyle: React.CSSProperties = {
  background: '#fff', borderRadius: 16, width: 'min(760px, 100%)',
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

/** «1 сотрудник», «2 сотрудника», «5 сотрудников». */
export function employeesLabel(count: number): string {
  const mod10 = count % 10;
  const mod100 = count % 100;
  let word = 'сотрудников';
  if (mod10 === 1 && mod100 !== 11) word = 'сотрудник';
  else if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) word = 'сотрудника';
  return `${count} ${word}`;
}

function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} КБ`;
  return `${formatDecimal(Math.round((bytes / 1024 / 1024) * 10) / 10)} МБ`;
}

function ItemLine({ item, assigned }: { item: KpItem; assigned?: boolean }) {
  return (
    <div style={{
      display: 'flex', gap: 10, alignItems: 'baseline', padding: '5px 0',
      borderBottom: '1px solid #f1f5f9', fontSize: 13,
    }}>
      <span style={{ width: 56, flexShrink: 0, color: '#94a3b8' }}>{item.source_no ?? ''}</span>
      <span style={{ flex: 1, minWidth: 0 }}>
        {item.name}
        {assigned && <span style={{ color: '#64748b', fontSize: 12 }}> · отнесено вами</span>}
      </span>
      <span style={{ color: '#64748b', whiteSpace: 'nowrap' }}>
        {item.qty !== null ? formatDecimal(item.qty) : '—'} {item.unit ?? ''}
      </span>
    </div>
  );
}

const RequestKpDialog: React.FC<Props> = ({
  cardId, kind, versionId, rowIds, isDirty, onClose, onCreated,
}) => {
  const [data, setData] = useState<KpPreview | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<Record<number, Decision>>({});
  const [comment, setComment] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [rejected, setRejected] = useState<Array<{ name: string; reason: string }>>([]);
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Ключи строк фиксируются при открытии: выделение в таблице под окном может
  // поменяться, а предпросмотр уже показан по прежнему.
  const rowIdsRef = useRef(rowIds);

  useEffect(() => {
    let cancelled = false;
    previewKpRequest({ card_id: cardId, kind, version_id: versionId, row_ids: rowIdsRef.current })
      .then((result) => { if (!cancelled) setData(result); })
      .catch((error) => {
        if (!cancelled) setLoadError(kpErrorText(error, 'Не удалось разобрать выделение на позиции запроса'));
      });
    return () => { cancelled = true; };
  }, [cardId, kind, versionId]);

  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !sending) onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose, sending]);

  const employees = useCallback(
    (category: KpCategory) => data?.groups[category].employees ?? 0,
    [data],
  );

  const unknownItems = data?.groups.unknown.items ?? [];
  const unresolved = unknownItems.filter((_, index) => decisions[index] === undefined).length;

  // Позиции каждой группы: свои и отнесённые человеком.
  const groups = useMemo(() => CATEGORIES.map((category) => {
    const own = data?.groups[category].items ?? [];
    const assigned = unknownItems.filter((_, index) => decisions[index] === category);
    const rows = [...own, ...assigned].flatMap((item) => item.source_row_ids);
    return {
      category,
      own,
      assigned,
      rowIds: rows,
      employees: employees(category),
      sendable: rows.length > 0 && employees(category) > 0,
    };
  }), [data, unknownItems, decisions, employees]);

  const toSend = groups.filter((group) => group.sendable);
  const blockedByRole = groups.some((group) => group.rowIds.length > 0 && group.employees === 0);

  let blockedReason: string | null = null;
  if (data) {
    if (unresolved > 0) {
      blockedReason = `Отнесите позиции без типа к материалам или работам — осталось ${unresolved}`;
    } else if (toSend.length === 0) {
      blockedReason = blockedByRole
        ? 'Отправлять некому: нет активных сотрудников нужной роли'
        : 'В выделении нет позиций для запроса';
    }
  }

  const handleFiles = (list: FileList | null) => {
    if (!list || list.length === 0) return;
    const { accepted, rejected: bad } = checkKpAttachments(Array.from(list), files.length);
    setFiles((previous) => [...previous, ...accepted]);
    setRejected(bad);
    // Тот же файл можно выбрать снова после «Убрать».
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleSend = async () => {
    if (!data || blockedReason || sending) return;
    setSending(true);
    setSendError(null);
    try {
      const result = await createKpRequests({
        card_id: cardId,
        kind,
        // Версия — та, по которой сервер показал предпросмотр: иначе между
        // открытием окна и отправкой запрос мог бы уйти по другой версии.
        version_id: data.version_id,
        author_comment: comment.trim() || null,
        groups: toSend.map((group) => ({ category: group.category, row_ids: group.rowIds })),
      }, files);
      onCreated(result.requests);
    } catch (error) {
      setSendError(kpErrorText(error, 'Не удалось отправить запрос КП'));
    } finally {
      setSending(false);
    }
  };

  const sendDisabled = !data || blockedReason !== null || sending;

  return (
    <div style={overlayStyle} role="dialog" aria-modal="true" aria-label="Запрос КП">
      <div style={modalStyle}>
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 18px', borderBottom: '1px solid #e2e8f0',
        }}>
          <b style={{ fontSize: 15 }}>Запросить КП у отдела производства работ</b>
          <button
            type="button" style={{ ...buttonStyle, border: 'none', padding: '0 6px' }}
            onClick={onClose} disabled={sending} aria-label="Закрыть"
          >
            <X size={16} />
          </button>
        </div>

        <div style={{ overflowY: 'auto', padding: '14px 18px', display: 'flex', flexDirection: 'column', gap: 12 }}>
          {isDirty && (
            <div style={noteStyle('warn')}>
              <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                В таблице есть непринятые правки. В запрос уйдут позиции из последнего
                применённого документа — нажмите «Применить», если правки нужны в запросе.
              </span>
            </div>
          )}

          {!data && !loadError && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, color: '#64748b' }}>
              <LumaSpin size="sm" color="#3b82f6" /> Собираю позиции запроса…
            </div>
          )}
          {loadError && <div style={noteStyle('error')} role="alert">{loadError}</div>}

          {data && (
            <>
              {groups.map((group) => {
                const total = group.own.length + group.assigned.length;
                if (total === 0) return null;
                const role = data.groups[group.category].target_role ?? '';
                return (
                  <section
                    key={group.category}
                    data-testid={`kp-group-${group.category}`}
                    style={{
                      border: `1px solid ${group.employees === 0 ? '#fecaca' : '#e2e8f0'}`,
                      borderRadius: 12, padding: '10px 14px',
                      background: group.employees === 0 ? '#fffafa' : '#fff',
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                      <b style={{ fontSize: 14 }}>
                        {KP_CATEGORY_LABELS[group.category]} → {KP_DEPARTMENT_LABELS[group.category]}
                      </b>
                      <span style={{ fontSize: 12, color: '#64748b' }}>
                        ({employeesLabel(group.employees)})
                      </span>
                      <span style={{ marginLeft: 'auto', fontSize: 12, color: '#64748b' }}>
                        позиций: {total}
                      </span>
                    </div>
                    {group.employees === 0 && (
                      <div style={{ ...noteStyle('error'), marginTop: 8 }}>
                        Нет активных сотрудников с ролью «{ROLE_LABELS[role] ?? role}» — эта группа
                        не будет отправлена. Заведите сотрудника на странице «Сотрудники».
                      </div>
                    )}
                    <div style={{ marginTop: 6, maxHeight: 180, overflowY: 'auto' }}>
                      {group.own.map((item, index) => (
                        <ItemLine key={`own-${index}`} item={item} />
                      ))}
                      {group.assigned.map((item, index) => (
                        <ItemLine key={`assigned-${index}`} item={item} assigned />
                      ))}
                    </div>
                  </section>
                );
              })}

              {unknownItems.length > 0 && (
                <section
                  data-testid="kp-group-unknown"
                  style={{ border: '1px solid #fcd34d', borderRadius: 12, padding: '10px 14px', background: '#fffdf5' }}
                >
                  <b style={{ fontSize: 14 }}>Не определено</b>
                  <div style={{ fontSize: 12, color: '#92400e', marginTop: 2 }}>
                    У этих позиций в документе не указан тип. Отнесите каждую к материалам
                    или работам — или не запрашивайте.
                  </div>
                  <div style={{ marginTop: 6 }}>
                    {unknownItems.map((item, index) => (
                      <div
                        key={index}
                        style={{
                          display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap',
                          padding: '6px 0', borderBottom: '1px solid #fef3c7', fontSize: 13,
                        }}
                      >
                        <span style={{ flex: 1, minWidth: 200 }}>
                          {item.name}
                          <span style={{ color: '#64748b' }}>
                            {' '}· {item.qty !== null ? formatDecimal(item.qty) : '—'} {item.unit ?? ''}
                          </span>
                        </span>
                        {([
                          ['material', 'Материал'], ['work', 'Работа'], ['skip', 'Не запрашивать'],
                        ] as Array<[Decision, string]>).map(([value, label]) => {
                          const noRole = value !== 'skip' && employees(value) === 0;
                          return (
                            <label
                              key={value}
                              title={noRole ? 'Нет активных сотрудников этой роли' : undefined}
                              style={{
                                display: 'inline-flex', gap: 4, alignItems: 'center',
                                color: noRole ? '#94a3b8' : '#334155',
                                cursor: noRole ? 'not-allowed' : 'pointer',
                              }}
                            >
                              <input
                                type="radio"
                                name={`kp-unknown-${index}`}
                                value={value}
                                checked={decisions[index] === value}
                                disabled={noRole || sending}
                                onChange={() => setDecisions((prev) => ({ ...prev, [index]: value }))}
                              />
                              {label}
                            </label>
                          );
                        })}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {data.skipped > 0 && (
                <div style={noteStyle('info')}>
                  Разделы и строки без наименования в запрос не попадают: {data.skipped}
                </div>
              )}
              {data.missing_row_ids.length > 0 && (
                <div style={noteStyle('warn')}>
                  Отмеченных строк нет в применённом документе: {data.missing_row_ids.length}.
                  Новые и непринятые строки попадут в запрос только после «Применить».
                </div>
              )}

              <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 13 }}>
                <span style={{ fontWeight: 600, color: '#374151' }}>Комментарий</span>
                <textarea
                  aria-label="Комментарий к запросу"
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  maxLength={10000}
                  rows={3}
                  placeholder="Сроки, адрес объекта, требования к поставщику…"
                  style={{
                    resize: 'vertical', padding: '8px 10px', border: '1px solid #e2e8f0',
                    borderRadius: 8, fontSize: 13, fontFamily: 'inherit',
                  }}
                />
              </label>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 13 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, color: '#374151' }}>Вложения</span>
                  <span style={{ color: '#94a3b8', fontSize: 12 }}>
                    PDF, XLSX, XLS, DOC, DOCX, JPG, PNG · до 50 МБ · до {KP_MAX_FILES} файлов
                  </span>
                  <button
                    type="button" style={{ ...buttonStyle, marginLeft: 'auto' }}
                    onClick={() => fileInputRef.current?.click()}
                    disabled={sending || files.length >= KP_MAX_FILES}
                  >
                    <Paperclip size={14} /> Приложить
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    hidden
                    aria-label="Приложить файлы"
                    accept=".pdf,.xlsx,.xls,.doc,.docx,.jpg,.jpeg,.png"
                    onChange={(e) => handleFiles(e.target.files)}
                  />
                </div>
                {files.map((file, index) => (
                  <div key={`${file.name}#${index}`} style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                    <span>{file.name}</span>
                    <span style={{ color: '#94a3b8', fontSize: 12 }}>{formatSize(file.size)}</span>
                    <button
                      type="button"
                      style={{ ...buttonStyle, height: 24, padding: '0 6px', border: 'none' }}
                      aria-label={`Убрать файл ${file.name}`}
                      disabled={sending}
                      onClick={() => setFiles((prev) => prev.filter((_, i) => i !== index))}
                    >
                      <X size={13} />
                    </button>
                  </div>
                ))}
                {rejected.map((item, index) => (
                  <div key={`rejected-${index}`} style={{ color: '#b91c1c', fontSize: 12 }}>
                    {item.name} — {item.reason}
                  </div>
                ))}
              </div>
            </>
          )}

          {sendError && <div style={noteStyle('error')} role="alert">{sendError}</div>}
        </div>

        <div style={{
          padding: '12px 18px', borderTop: '1px solid #e2e8f0',
          display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        }}>
          {blockedReason ? (
            <span data-testid="kp-send-blocked" style={{ fontSize: 12, color: '#b45309', flex: 1, minWidth: 200 }}>
              {blockedReason}
            </span>
          ) : (
            <span style={{ fontSize: 12, color: '#64748b', flex: 1, minWidth: 200 }}>
              {data && toSend.length > 0 && (
                `Будет создано запросов: ${toSend.length} — `
                + toSend.map((group) => KP_DEPARTMENT_LABELS[group.category]).join(', ')
              )}
            </span>
          )}
          <button type="button" style={buttonStyle} onClick={onClose} disabled={sending}>
            Отмена
          </button>
          <button
            type="button"
            style={primaryStyle(sendDisabled)}
            onClick={handleSend}
            disabled={sendDisabled}
          >
            {sending ? <LumaSpin size="sm" color="#94a3b8" /> : <Send size={14} />}
            Отправить
          </button>
        </div>
      </div>
    </div>
  );
};

export default RequestKpDialog;
