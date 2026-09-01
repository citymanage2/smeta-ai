import React, { useCallback, useEffect, useState } from 'react';
import {
  ApiBalance,
  createBalanceMark,
  deleteBalanceMark,
  fetchApiBalance,
  syncApiBalance,
} from '../../api/apiBalance';

/**
 * Остаток денег на Claude API.
 *
 * Главное на блоке — не сумма, а ответ на вопрос «когда встанет работа»: деньги
 * кончаются молча, и до этой карточки единственным сигналом были задачи,
 * упавшие в паузу посреди подготовки к аукциону. Поэтому «хватит примерно на N
 * дней» стоит рядом с суммой, а не прячется в подпись.
 *
 * Остатка не отдаёт ни один эндпоинт Anthropic, точку отсчёта вводит человек —
 * отсюда кнопка «Сверить с Console» и честная подпись, когда отметка устарела.
 */

interface Props {
  /** Обновить остальной дашборд после сверки — цифры трат общие. */
  onChanged?: () => void;
}

const LEVEL_COLORS: Record<ApiBalance['level'], { text: string; bg: string; border: string }> = {
  ok: { text: '#16a34a', bg: '#f0fdf4', border: '#bbf7d0' },
  warn: { text: '#d97706', bg: '#fffbeb', border: '#fde68a' },
  alarm: { text: '#dc2626', bg: '#fef2f2', border: '#fecaca' },
  unknown: { text: '#64748b', bg: '#f8fafc', border: '#e2e8f0' },
};

function formatUsd(value: number): string {
  return `$${value.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit', year: 'numeric' });
}

function formatDateTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** «Хватит на N дней» словами: 0.8 дня — это «меньше суток», а не «0.8 дн.». */
function formatDaysLeft(days: number | null): string {
  if (days === null) return 'расход пока нулевой — прогноз не построить';
  if (days < 1) return 'хватит меньше чем на сутки';
  if (days < 2) return 'хватит примерно на день';
  const rounded = Math.floor(days);
  if (rounded > 90) return 'хватит больше чем на три месяца';
  const tail = rounded % 10;
  const teen = rounded % 100 >= 11 && rounded % 100 <= 14;
  const word = !teen && tail === 1 ? 'день' : !teen && tail >= 2 && tail <= 4 ? 'дня' : 'дней';
  return `хватит примерно на ${rounded} ${word}`;
}

const DashboardBalance: React.FC<Props> = ({ onChanged }) => {
  const [data, setData] = useState<ApiBalance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formOpen, setFormOpen] = useState(false);
  const [amount, setAmount] = useState('');
  const [measuredOn, setMeasuredOn] = useState(() => new Date().toISOString().slice(0, 10));

  const load = useCallback(async () => {
    try {
      setData(await fetchApiBalance());
      setError(null);
    } catch {
      setError('Не удалось загрузить остаток');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSync = async () => {
    setBusy(true);
    try {
      const next = await syncApiBalance();
      setData(next);
      // Ответ Anthropic показываем как есть: по нему видно, что чинить —
      // ключ, доступ прокси к /v1/organizations или тип организации.
      setError(next.sync_error ? `Сверка не прошла. ${next.sync_error}` : null);
      onChanged?.();
    } catch {
      setError('Сверка с Anthropic не удалась — показан расчёт по своему журналу');
    } finally {
      setBusy(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const value = Number(amount.replace(',', '.'));
    if (!Number.isFinite(value) || value <= 0) {
      setError('Введите сумму больше нуля');
      return;
    }
    setBusy(true);
    try {
      setData(await createBalanceMark(value, measuredOn));
      setAmount('');
      setFormOpen(false);
      setError(null);
    } catch {
      setError('Не удалось сохранить отметку');
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async (id: number) => {
    setBusy(true);
    try {
      setData(await deleteBalanceMark(id));
      setError(null);
    } catch {
      setError('Не удалось удалить отметку');
    } finally {
      setBusy(false);
    }
  };

  if (!data) {
    return (
      <div style={{ fontSize: 13, color: '#94a3b8' }}>
        {error || 'Загрузка остатка...'}
      </div>
    );
  }

  const colors = LEVEL_COLORS[data.level];
  const known = data.remaining_usd !== null;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, color: '#374151', margin: 0 }}>
          Остаток на Claude API
        </h2>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={handleSync}
            disabled={busy || !data.official_enabled}
            title={
              data.official_enabled
                ? 'Запросить у Anthropic официальные траты за последние дни'
                : 'Не задан ключ Anthropic — сверять нечем'
            }
            style={btnStyle(busy || !data.official_enabled)}
          >
            Сверить траты
          </button>
          <button onClick={() => setFormOpen(v => !v)} disabled={busy} style={btnStyle(busy, true)}>
            {formOpen ? 'Отмена' : 'Внести баланс'}
          </button>
        </div>
      </div>

      {error && (
        <div style={{ fontSize: 12, color: '#dc2626', marginBottom: 12 }}>{error}</div>
      )}

      {/* Главная цифра */}
      <div
        style={{
          backgroundColor: colors.bg,
          border: `1px solid ${colors.border}`,
          borderRadius: 12,
          padding: '20px 24px',
          marginBottom: 16,
        }}
      >
        {known ? (
          <>
            <div
              style={{
                fontSize: 34,
                fontWeight: 700,
                color: colors.text,
                lineHeight: 1.1,
                fontVariantNumeric: 'tabular-nums',
              }}
            >
              {formatUsd(data.remaining_usd as number)}
            </div>
            <div style={{ fontSize: 14, color: colors.text, marginTop: 6 }}>
              {(data.remaining_usd as number) <= 0
                ? 'Деньги кончились — либо счёт пополнили и не отметили'
                : formatDaysLeft(data.days_left)}
              {data.estimates_left !== null && (data.remaining_usd as number) > 0 && (
                <span style={{ color: '#64748b' }}>
                  {' '}· это примерно {data.estimates_left} смет
                </span>
              )}
            </div>
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 8 }}>
              От отметки {formatUsd(data.mark_usd as number)} на {formatDate(data.mark_on)} ·
              потрачено с тех пор {formatUsd(data.spent_usd)}
              {data.avg_daily_usd > 0 && <> · темп {formatUsd(data.avg_daily_usd)}/день</>}
            </div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 20, fontWeight: 600, color: '#475569' }}>
              Остаток неизвестен
            </div>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 6, maxWidth: 640 }}>
              Anthropic не отдаёт баланс счёта ни одним запросом — точку отсчёта нужно
              задать руками. Откройте Console, посмотрите остаток кредитов и нажмите
              «Внести баланс». Дальше сервис вычитает из него собственные траты сам.
            </div>
            {data.avg_daily_usd > 0 && (
              <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 8 }}>
                Текущий темп расхода — {formatUsd(data.avg_daily_usd)} в день.
              </div>
            )}
          </>
        )}
      </div>

      {/* Форма отметки */}
      {formOpen && (
        <form
          onSubmit={handleSubmit}
          style={{
            display: 'flex',
            gap: 10,
            alignItems: 'flex-end',
            padding: '14px 16px',
            backgroundColor: '#f8fafc',
            border: '1px solid #e2e8f0',
            borderRadius: 8,
            marginBottom: 16,
            flexWrap: 'wrap',
          }}
        >
          <label style={labelStyle}>
            Остаток по данным Console, $
            <input
              autoFocus
              value={amount}
              onChange={e => setAmount(e.target.value)}
              placeholder="500"
              inputMode="decimal"
              style={inputStyle}
            />
          </label>
          <label style={labelStyle}>
            На дату
            <input
              type="date"
              value={measuredOn}
              max={new Date().toISOString().slice(0, 10)}
              onChange={e => setMeasuredOn(e.target.value)}
              style={inputStyle}
            />
          </label>
          <button type="submit" disabled={busy} style={btnStyle(busy, true)}>
            Сохранить
          </button>
          <span style={{ fontSize: 12, color: '#94a3b8', flexBasis: '100%' }}>
            Траты этого дня будут вычтены полностью — остаток может оказаться чуть
            меньше настоящего, но никогда не больше.
          </span>
        </form>
      )}

      {/* Откуда цифры */}
      <div style={{ fontSize: 12, color: '#94a3b8', display: 'flex', gap: 16, flexWrap: 'wrap' }}>
        <span>
          Сегодня по своему журналу: <b style={{ color: '#64748b' }}>{formatUsd(data.live_usd)}</b>
        </span>
        {data.official_enabled ? (
          data.synced_at ? (
            <span>
              Официально подтверждено Anthropic по {formatDate(data.official_through)} ·
              сверка {formatDateTime(data.synced_at)}
            </span>
          ) : (
            // Нейтрально, без намёка на поломку: официальной сверки может не
            // быть никогда (на личной организации Anthropic её не даёт), а
            // остаток от этого не становится менее рабочим.
            <span>Официальная сверка с Anthropic: данных нет</span>
          )
        ) : (
          <span>Ключ Anthropic не задан — всё считается по своему журналу</span>
        )}
      </div>

      {/* История отметок */}
      {data.marks.length > 0 && (
        <details style={{ marginTop: 14 }}>
          <summary style={{ fontSize: 12, color: '#64748b', cursor: 'pointer' }}>
            Отметки баланса ({data.marks.length})
          </summary>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {data.marks.map(mark => (
              <div
                key={mark.id}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 10,
                  fontSize: 12,
                  color: '#64748b',
                }}
              >
                <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                  {formatDate(mark.measured_on)}
                </span>
                <b style={{ color: '#334155' }}>{formatUsd(mark.balance_usd)}</b>
                {mark.created_by && <span style={{ color: '#94a3b8' }}>{mark.created_by}</span>}
                <button
                  onClick={() => handleDelete(mark.id)}
                  disabled={busy}
                  style={{
                    marginLeft: 'auto',
                    fontSize: 12,
                    border: 'none',
                    background: 'none',
                    color: '#dc2626',
                    cursor: busy ? 'default' : 'pointer',
                  }}
                >
                  Удалить
                </button>
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  );
};

function btnStyle(disabled: boolean, primary = false): React.CSSProperties {
  return {
    fontSize: 13,
    padding: '6px 14px',
    borderRadius: 7,
    border: `1px solid ${primary ? '#2563eb' : '#e2e8f0'}`,
    backgroundColor: primary ? '#2563eb' : '#f8fafc',
    color: primary ? '#ffffff' : '#64748b',
    cursor: disabled ? 'default' : 'pointer',
    opacity: disabled ? 0.6 : 1,
  };
}

const labelStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: 4,
  fontSize: 12,
  color: '#64748b',
};

const inputStyle: React.CSSProperties = {
  fontSize: 13,
  padding: '6px 10px',
  border: '1px solid #e2e8f0',
  borderRadius: 7,
  minWidth: 150,
};

export default DashboardBalance;
