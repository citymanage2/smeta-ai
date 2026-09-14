import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Paperclip } from 'lucide-react';

import Layout from '../components/Layout';
import { kpErrorText, listMyKpRequests } from '../api/kpRequests';
import { useAuthStore } from '../stores/auth';
import {
  KP_CATEGORY_LABELS, KP_STATUS_LABELS, KpRequestBrief, KpStatus,
} from '../types/kp';

/**
 * «Мои задачи КП» — входящие отдела производства работ
 * (план plans/2026-09-14-zapros-kp.md, фаза 5, критерии 13–14).
 *
 * Запрос адресован роли целиком, поэтому здесь все запросы своей роли — и
 * взятые коллегами: видно, у кого запрос, но работать с ним может любой.
 * Вкладки — «Новые / В работе / Завершённые»; отменённые автором лежат в
 * «Завершённых» со своим статусом: работы по ним больше нет.
 *
 * Список перечитывается раз в 30 секунд при видимой вкладке — новый запрос
 * появляется без перезагрузки (почты нет, решение пользователя 14.09.2026).
 * Каждый статус — отдельным запросом к серверу: у списка есть предел, и
 * старые завершённые не должны вытеснять новые.
 */

type Tab = 'new' | 'in_progress' | 'closed';

const TABS: Array<{ id: Tab; label: string; statuses: KpStatus[]; empty: string }> = [
  { id: 'new', label: 'Новые', statuses: ['new'], empty: 'Новых запросов нет.' },
  { id: 'in_progress', label: 'В работе', statuses: ['in_progress'], empty: 'Запросов в работе нет.' },
  { id: 'closed', label: 'Завершённые', statuses: ['done', 'cancelled'], empty: 'Завершённых запросов пока нет.' },
];

const POLL_MS = 30_000;

const th: React.CSSProperties = {
  textAlign: 'left', padding: '8px 12px', fontSize: 12, fontWeight: 600, color: '#64748b',
  borderBottom: '1px solid #e2e8f0', whiteSpace: 'nowrap',
};
const td: React.CSSProperties = {
  padding: '10px 12px', fontSize: 14, color: '#334155', borderBottom: '1px solid #f1f5f9',
  verticalAlign: 'top',
};

function formatDate(value: string | null): string {
  if (!value) return '';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('ru-RU');
}

type Lists = Record<KpStatus, KpRequestBrief[]>;
const EMPTY_LISTS: Lists = { new: [], in_progress: [], done: [], cancelled: [] };

const KpInbox: React.FC = () => {
  const navigate = useNavigate();
  const isProduction = useAuthStore((state) => state.isProduction);
  const [tab, setTab] = useState<Tab>('new');
  const [lists, setLists] = useState<Lists>(EMPTY_LISTS);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const aliveRef = useRef(true);

  const load = useCallback(async () => {
    try {
      const statuses: KpStatus[] = ['new', 'in_progress', 'done', 'cancelled'];
      const results = await Promise.all(statuses.map((s) => listMyKpRequests(s)));
      if (!aliveRef.current) return;
      const next = { ...EMPTY_LISTS };
      statuses.forEach((s, i) => { next[s] = results[i] ?? []; });
      setLists(next);
      setError(null);
    } catch (err) {
      if (aliveRef.current) setError(kpErrorText(err, 'Не удалось загрузить запросы КП'));
    } finally {
      if (aliveRef.current) setLoaded(true);
    }
  }, []);

  useEffect(() => {
    aliveRef.current = true;
    load();
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
    return () => {
      aliveRef.current = false;
      window.clearInterval(timer);
    };
  }, [load]);

  const current = TABS.find((t) => t.id === tab) ?? TABS[0];
  const rows = current.statuses
    .flatMap((s) => lists[s])
    .sort((a, b) => (b.completed_at ?? b.created_at).localeCompare(a.completed_at ?? a.created_at));

  return (
    <Layout>
      <div style={{ maxWidth: 1100, display: 'flex', flexDirection: 'column', gap: 16 }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#1e293b', margin: 0 }}>
          {isProduction ? 'Мои задачи КП' : 'Мои запросы КП'}
        </h1>

        <div role="tablist" style={{ display: 'flex', gap: 4, borderBottom: '1px solid #e2e8f0', flexWrap: 'wrap' }}>
          {TABS.map((t) => {
            const count = t.statuses.reduce((sum, s) => sum + lists[s].length, 0);
            const active = t.id === tab;
            return (
              <button
                key={t.id}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setTab(t.id)}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6, padding: '8px 14px',
                  border: 'none', background: 'transparent', cursor: 'pointer', fontSize: 14,
                  fontWeight: active ? 600 : 500, color: active ? '#2563eb' : '#64748b',
                  borderBottom: active ? '2px solid #2563eb' : '2px solid transparent', marginBottom: -1,
                }}
              >
                {t.label}
                <span style={{
                  fontSize: 12, fontWeight: 600, borderRadius: 12, padding: '0 8px',
                  background: active ? '#eff6ff' : '#f1f5f9', color: active ? '#1d4ed8' : '#64748b',
                }}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>

        {error && (
          <div role="alert" style={{
            fontSize: 14, color: '#b91c1c', background: '#fef2f2', border: '1px solid #fecaca',
            borderRadius: 8, padding: '8px 12px',
          }}>
            {error}
          </div>
        )}

        <div style={{ background: '#ffffff', border: '1px solid #e2e8f0', borderRadius: 16, overflowX: 'auto' }}>
          {rows.length === 0 ? (
            <div style={{ padding: 16, color: '#64748b', fontSize: 14 }}>
              {loaded ? current.empty : 'Загрузка…'}
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760 }}>
              <thead>
                <tr>
                  <th style={th}>Объект</th>
                  <th style={th}>Что запрошено</th>
                  <th style={th}>Автор</th>
                  <th style={th}>Позиций</th>
                  <th style={th}>Поставлен</th>
                  <th style={th}>Кто взял</th>
                  {tab === 'closed' && <th style={th}>Статус</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={r.id}
                    data-testid={`kp-inbox-row-${r.id}`}
                    onClick={() => navigate(`/kp/${r.id}`)}
                    onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/kp/${r.id}`); }}
                    tabIndex={0}
                    style={{ cursor: 'pointer' }}
                  >
                    <td style={td}>
                      <div style={{ color: '#1e293b', fontWeight: 500 }}>{r.project_name ?? '—'}</div>
                      {r.card_name && <div style={{ fontSize: 12, color: '#94a3b8' }}>{r.card_name}</div>}
                    </td>
                    <td style={td}>
                      {KP_CATEGORY_LABELS[r.category]}
                      {r.files_count > 0 && (
                        <span style={{ marginLeft: 8, color: '#94a3b8', fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 2 }}>
                          <Paperclip size={11} /> {r.files_count}
                        </span>
                      )}
                    </td>
                    <td style={td}>{r.author_name ?? '—'}</td>
                    <td style={td}>{r.items_count}</td>
                    <td style={{ ...td, whiteSpace: 'nowrap' }}>{formatDate(r.created_at)}</td>
                    <td style={td}>{r.taken_by_name ?? <span style={{ color: '#94a3b8' }}>—</span>}</td>
                    {tab === 'closed' && (
                      <td style={td}>
                        {KP_STATUS_LABELS[r.status] ?? r.status}
                        {r.completed_at && (
                          <div style={{ fontSize: 12, color: '#94a3b8' }}>{formatDate(r.completed_at)}</div>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </Layout>
  );
};

export default KpInbox;
