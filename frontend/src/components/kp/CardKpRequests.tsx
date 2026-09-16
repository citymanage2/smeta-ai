import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronDown, ChevronRight, FileText, Paperclip, Trash2 } from 'lucide-react';
import { Link, useInRouterContext } from 'react-router-dom';

import {
  addKpRequestFiles, cancelKpRequest, checkKpAttachments, currentUserIdFromToken,
  deleteKpRequestFile, getKpRequest, kpErrorText, kpFileDownloadUrl,
  listCardKpRequests, reopenKpRequest,
} from '../../api/kpRequests';
import { useAuthStore } from '../../stores/auth';
import { formatDecimal } from '../../utils/formatNumber';
import {
  KP_CATEGORY_LABELS, KP_DEPARTMENT_LABELS, KP_MAX_FILES, KP_STATUS_LABELS,
  KpRequestBrief, KpRequestDetail, KpStatus,
} from '../../types/kp';

/**
 * Запросы КП в карточке сметы (план plans/2026-09-14-zapros-kp.md, фаза 3,
 * критерий 29).
 *
 * Менеджер продаж видит здесь, что уже запрошено по смете, у кого запрос и
 * сколько КП получено, но ещё не применено. Статусы меняет отдел производства
 * у себя, поэтому список перечитывается раз в 30 секунд, пока вкладка видна.
 *
 * Права решает сервер; кнопки «Отменить» и «Вернуть в работу» показываются
 * автору и руководителю продаж — тем же, кому сервер их разрешит.
 */

interface Props {
  cardId: string;
  /** Меняется, когда запрос поставили из редактора на этой же странице. */
  refreshKey?: number;
}

const POLL_MS = 30_000;

const STATUS_COLORS: Record<KpStatus, { bg: string; fg: string }> = {
  new: { bg: '#eff6ff', fg: '#1d4ed8' },
  in_progress: { bg: '#fffbeb', fg: '#b45309' },
  done: { bg: '#f0fdf4', fg: '#15803d' },
  cancelled: { bg: '#f1f5f9', fg: '#64748b' },
};

const smallButton: React.CSSProperties = {
  display: 'inline-flex', alignItems: 'center', gap: 4, height: 26, padding: '0 10px',
  borderRadius: 7, border: '1px solid #e2e8f0', background: '#fff', color: '#475569',
  fontSize: 12, fontWeight: 500, cursor: 'pointer', whiteSpace: 'nowrap',
};

function formatDate(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('ru-RU');
}

/**
 * Переход на страницу запроса (сравнение КП, выбор, отчёт). Внутри роутера —
 * ссылкой без перезагрузки; вне роутера (отдельный показ блока) — обычной.
 */
function RequestPageLink({ requestId }: { requestId: string }) {
  const inRouter = useInRouterContext();
  const style: React.CSSProperties = { ...smallButton, textDecoration: 'none' };
  const to = `/kp/${requestId}`;
  return inRouter
    ? <Link to={to} style={style}>КП и цены</Link>
    : <a href={to} style={style}>КП и цены</a>;
}

function Details({
  detail, busy, onAddFiles, onDeleteFile,
}: {
  detail: KpRequestDetail;
  busy: boolean;
  onAddFiles: (files: File[]) => void;
  onDeleteFile: (fileId: string, name: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [rejected, setRejected] = useState<string[]>([]);
  const canEditFiles = detail.permissions.can_edit_files;

  return (
    <div
      data-testid={`kp-request-details-${detail.id}`}
      style={{ padding: '8px 12px 12px 30px', fontSize: 13, color: '#334155' }}
    >
      {detail.author_comment && (
        <div style={{ marginBottom: 8, whiteSpace: 'pre-wrap' }}>
          <span style={{ color: '#64748b' }}>Комментарий: </span>{detail.author_comment}
        </div>
      )}
      <div style={{ border: '1px solid #f1f5f9', borderRadius: 8, maxHeight: 220, overflowY: 'auto' }}>
        {detail.items.map((item) => (
          <div
            key={item.id ?? item.position}
            style={{ display: 'flex', gap: 10, padding: '4px 10px', borderBottom: '1px solid #f8fafc' }}
          >
            <span style={{ width: 48, flexShrink: 0, color: '#94a3b8' }}>{item.source_no ?? ''}</span>
            <span style={{ flex: 1, minWidth: 0 }}>{item.name}</span>
            <span style={{ color: '#64748b', whiteSpace: 'nowrap' }}>
              {item.qty !== null ? formatDecimal(item.qty) : '—'} {item.unit ?? ''}
            </span>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontWeight: 600, color: '#374151' }}>Вложения</span>
          {canEditFiles && (
            <>
              <button
                type="button"
                style={smallButton}
                disabled={busy || detail.files.length >= KP_MAX_FILES}
                onClick={() => inputRef.current?.click()}
              >
                <Paperclip size={12} /> Добавить
              </button>
              <input
                ref={inputRef}
                type="file"
                multiple
                hidden
                aria-label="Добавить вложения"
                accept=".pdf,.xlsx,.xls,.doc,.docx,.jpg,.jpeg,.png"
                onChange={(e) => {
                  const list = e.target.files ? Array.from(e.target.files) : [];
                  if (inputRef.current) inputRef.current.value = '';
                  const { accepted, rejected: bad } = checkKpAttachments(list, detail.files.length);
                  setRejected(bad.map((item) => `${item.name} — ${item.reason}`));
                  if (accepted.length > 0) onAddFiles(accepted);
                }}
              />
            </>
          )}
        </div>
        {detail.files.length === 0 && <span style={{ color: '#94a3b8' }}>Нет вложений</span>}
        {detail.files.map((file) => (
          <div key={file.id} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FileText size={13} color="#64748b" />
            <a href={kpFileDownloadUrl(file.id)} target="_blank" rel="noreferrer" style={{ color: '#2563eb' }}>
              {file.file_name}
            </a>
            {file.uploaded_by_name && (
              <span style={{ color: '#94a3b8', fontSize: 12 }}>{file.uploaded_by_name}</span>
            )}
            {canEditFiles && (
              <button
                type="button"
                style={{ ...smallButton, border: 'none', padding: '0 4px', color: '#dc2626' }}
                disabled={busy}
                aria-label={`Удалить вложение ${file.file_name}`}
                onClick={() => onDeleteFile(file.id, file.file_name)}
              >
                <Trash2 size={12} />
              </button>
            )}
          </div>
        ))}
        {rejected.map((text, index) => (
          <span key={index} style={{ color: '#b91c1c', fontSize: 12 }}>{text}</span>
        ))}
      </div>
    </div>
  );
}

const CardKpRequests: React.FC<Props> = ({ cardId, refreshKey = 0 }) => {
  const isManager = useAuthStore((state) => state.isManager);
  const [requests, setRequests] = useState<KpRequestBrief[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [detail, setDetail] = useState<KpRequestDetail | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const aliveRef = useRef(true);
  // Какой запрос раскрыт сейчас. Ответ по запросу, который успели закрыть или
  // сменить другим, не должен ни подменить детали, ни показать чужую ошибку.
  const openRef = useRef<string | null>(null);

  useEffect(() => {
    aliveRef.current = true;
    return () => { aliveRef.current = false; };
  }, []);

  // Ответ по прежней карточке, пришедший после перехода на другую, не должен
  // подменить список новой.
  const cardRef = useRef(cardId);
  useEffect(() => {
    cardRef.current = cardId;
    openRef.current = null;
    setRequests([]);
    setOpenId(null);
    setDetail(null);
    setError(null);
  }, [cardId]);

  const reload = useCallback(async () => {
    try {
      const list = await listCardKpRequests(cardId);
      if (aliveRef.current && cardRef.current === cardId) setRequests(list);
    } catch {
      // Молча: список запросов — не повод ломать карточку сметы.
    }
  }, [cardId]);

  useEffect(() => {
    reload();
    const timer = setInterval(() => { if (!document.hidden) reload(); }, POLL_MS);
    return () => clearInterval(timer);
  }, [reload, refreshKey]);

  const loadDetail = useCallback(async (requestId: string) => {
    try {
      const data = await getKpRequest(requestId);
      if (aliveRef.current && openRef.current === requestId && data.id === requestId) setDetail(data);
    } catch (err) {
      if (aliveRef.current && openRef.current === requestId) {
        setError(kpErrorText(err, 'Не удалось открыть запрос КП'));
      }
    }
  }, []);

  const toggleOpen = (requestId: string) => {
    setError(null);
    if (openId === requestId) {
      openRef.current = null;
      setOpenId(null);
      setDetail(null);
      return;
    }
    openRef.current = requestId;
    setOpenId(requestId);
    setDetail(null);
    loadDetail(requestId);
  };

  const run = async (requestId: string, action: () => Promise<unknown>, fallback: string) => {
    setBusyId(requestId);
    setError(null);
    try {
      await action();
      await reload();
      if (openRef.current === requestId) await loadDetail(requestId);
    } catch (err) {
      if (aliveRef.current) setError(kpErrorText(err, fallback));
    } finally {
      if (aliveRef.current) setBusyId(null);
    }
  };

  if (requests.length === 0) return null;

  const myId = currentUserIdFromToken();
  const canManage = (request: KpRequestBrief) => (
    isManager || (myId !== null && request.author_id === myId)
  );
  const received = requests.filter((r) => r.status === 'done' && !r.applied_at).length;

  return (
    <section
      style={{
        marginTop: 16, background: 'rgba(255,255,255,0.9)', border: '1px solid #e2e8f0',
        borderRadius: 16, padding: '14px 18px', boxShadow: '0 4px 24px rgba(0,0,0,0.04)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <b style={{ fontSize: 14, color: '#0f172a' }}>Запросы КП</b>
        <span style={{ fontSize: 12, color: '#94a3b8' }}>{requests.length}</span>
        {received > 0 && (
          <span style={{
            fontSize: 12, fontWeight: 600, color: '#15803d', background: '#f0fdf4',
            border: '1px solid #bbf7d0', borderRadius: 12, padding: '1px 10px',
          }}>
            КП получены: {received}
          </span>
        )}
      </div>

      {error && (
        <div role="alert" style={{
          fontSize: 13, color: '#b91c1c', background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 8, padding: '6px 10px', marginBottom: 8,
        }}>
          {error}
        </div>
      )}

      {requests.map((request) => {
        const open = openId === request.id;
        const busy = busyId === request.id;
        const colors = STATUS_COLORS[request.status] ?? STATUS_COLORS.cancelled;
        const cancellable = request.status === 'new' || request.status === 'in_progress';
        const reopenable = request.status === 'done' || request.status === 'cancelled';
        return (
          <div key={request.id} style={{ borderTop: '1px solid #f1f5f9' }}>
            <div
              data-testid={`kp-request-${request.id}`}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                padding: '8px 0', fontSize: 13, color: '#334155',
              }}
            >
              <span style={{ fontWeight: 600, minWidth: 200 }}>
                {KP_CATEGORY_LABELS[request.category]}
                <span style={{ fontWeight: 400, color: '#64748b' }}>
                  {' '}→ {KP_DEPARTMENT_LABELS[request.category]}
                </span>
              </span>
              <span style={{
                fontSize: 12, fontWeight: 600, borderRadius: 12, padding: '1px 10px',
                background: colors.bg, color: colors.fg,
              }}>
                {KP_STATUS_LABELS[request.status] ?? request.status}
              </span>
              <span style={{ color: '#64748b' }}>
                {request.taken_by_name ? `Взял: ${request.taken_by_name}` : 'Никто не взял'}
              </span>
              <span style={{ color: '#64748b' }}>позиций: {request.items_count}</span>
              <span style={{ color: '#64748b', display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                <Paperclip size={12} /> {request.files_count}
              </span>
              <span style={{ color: '#94a3b8' }}>
                {formatDate(request.created_at)}
                {request.author_name ? ` · ${request.author_name}` : ''}
              </span>
              <span style={{ marginLeft: 'auto', display: 'inline-flex', gap: 6 }}>
                <RequestPageLink requestId={request.id} />
                <button type="button" style={smallButton} onClick={() => toggleOpen(request.id)}>
                  {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  {open ? 'Скрыть' : 'Открыть'}
                </button>
                {cancellable && canManage(request) && (
                  <button
                    type="button"
                    style={{ ...smallButton, color: '#dc2626' }}
                    disabled={busy}
                    onClick={() => {
                      if (!window.confirm('Отменить запрос КП? Отдел производства перестанет по нему работать.')) return;
                      run(request.id, () => cancelKpRequest(request.id), 'Не удалось отменить запрос');
                    }}
                  >
                    Отменить
                  </button>
                )}
                {reopenable && canManage(request) && (
                  <button
                    type="button"
                    style={smallButton}
                    disabled={busy}
                    onClick={() => {
                      if (!window.confirm('Вернуть запрос КП в работу отделу производства?')) return;
                      run(request.id, () => reopenKpRequest(request.id), 'Не удалось вернуть запрос в работу');
                    }}
                  >
                    Вернуть в работу
                  </button>
                )}
              </span>
            </div>
            {open && detail?.id === request.id && (
              <Details
                detail={detail}
                busy={busy}
                onAddFiles={(files) => run(
                  request.id, () => addKpRequestFiles(request.id, files), 'Не удалось приложить файлы',
                )}
                onDeleteFile={(fileId, name) => {
                  if (!window.confirm(`Удалить вложение «${name}»?`)) return;
                  run(request.id, () => deleteKpRequestFile(fileId), 'Не удалось удалить вложение');
                }}
              />
            )}
          </div>
        );
      })}
    </section>
  );
};

export default CardKpRequests;
