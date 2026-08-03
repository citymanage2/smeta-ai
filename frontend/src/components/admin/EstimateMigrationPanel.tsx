import React, { useCallback, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, PlayCircle, RefreshCw } from 'lucide-react';

import {
  MigrationEntry,
  MigrationReport,
  applyEstimateMigration,
  getEstimateMigrationReport,
  resolveEstimateConflict,
} from '../../api/admin';
import { LumaSpin } from '../ui/LumaSpin';

/**
 * Перевод смет на единый источник правды.
 *
 * Разовая операция после Фазы 5 плана единого редактора: сметам, посчитанным до
 * него, нужна рабочая версия, а часть смет разошлась между двумя хранилищами.
 * Раньше это чинилось командой в консоли сервера — здесь то же самое, но
 * кнопками и с отчётом на экране.
 *
 * Порядок намеренно в три шага: сначала проверка (ничего не меняется), потом
 * создание недостающих версий (активные тендеры можно исключить), и только
 * потом расхождения — по одному, с показом обоих итогов.
 */

const money = (n: number) => `${Math.round(n).toLocaleString('ru-RU')} ₽`;

const cardStyle: React.CSSProperties = {
  border: '1px solid #e2e8f0', borderRadius: 10, padding: 14, marginBottom: 12,
  background: '#fff',
};

const EstimateMigrationPanel: React.FC = () => {
  const [report, setReport] = useState<MigrationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [untouched, setUntouched] = useState<Set<string>>(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setReport(await getEstimateMigrationReport());
    } catch {
      setError('Не удалось получить отчёт. Попробуйте ещё раз.');
    } finally {
      setLoading(false);
    }
  }, []);

  const needsVersion = useMemo(
    () => (report?.entries ?? []).filter((e) => e.status === 'needs_version'),
    [report],
  );
  const conflicts = useMemo(
    () => (report?.entries ?? []).filter((e) => e.status === 'conflict'),
    [report],
  );
  // Сколько смет реально уйдёт в работу: отмеченные «не трогать» вычитаются.
  const toProcess = useMemo(
    () => needsVersion.filter((e) => !untouched.has(e.task_id)).length,
    [needsVersion, untouched],
  );

  const toggle = (taskId: string) => {
    setUntouched((prev) => {
      const next = new Set(prev);
      if (next.has(taskId)) next.delete(taskId);
      else next.add(taskId);
      return next;
    });
  };

  const handleApply = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await applyEstimateMigration([...untouched]);
      const created = result.counts.needs_version ?? 0;
      setNotice(`Создано рабочих версий: ${created}`);
      await load();
    } catch {
      setError('Не удалось выполнить перевод. Данные остались как были.');
    } finally {
      setBusy(false);
    }
  }, [untouched, load]);

  const handleResolve = useCallback(
    async (entry: MigrationEntry, prefer: 'items' | 'version') => {
      setBusy(true);
      setError(null);
      try {
        await resolveEstimateConflict(entry.task_id, prefer);
        setNotice(
          prefer === 'items'
            ? `«${entry.task_name}»: взяты цифры расчёта`
            : `«${entry.task_name}»: оставлено как в редакторе`,
        );
        await load();
      } catch {
        setError('Не удалось разобрать расхождение. Смета осталась как была.');
      } finally {
        setBusy(false);
      }
    },
    [load],
  );

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 16 }}>Перевод смет</h3>
        <p style={{ margin: 0, fontSize: 13, color: '#64748b', maxWidth: 760 }}>
          Сметам, посчитанным до перехода на единый редактор, нужна рабочая
          версия. Проверка ничего не меняет — она только показывает, что будет
          сделано. Сметы, где расчёт и редактор разошлись, разбираются по одной.
        </p>
      </div>

      <button
        className="de-btn"
        onClick={load}
        disabled={loading || busy}
        style={{
          padding: '8px 16px', borderRadius: 8, border: '1px solid #2563eb',
          background: '#2563eb', color: '#fff', cursor: 'pointer', fontSize: 14,
        }}
      >
        <RefreshCw size={14} style={{ verticalAlign: -2, marginRight: 6 }} />
        Проверить
      </button>

      {loading && (
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginTop: 14 }}>
          <LumaSpin size="sm" color="#3b82f6" /> Считаем…
        </div>
      )}

      {error && (
        <div style={{
          marginTop: 14, padding: 12, borderRadius: 8, background: '#fef2f2',
          color: '#b91c1c', fontSize: 13, display: 'flex', gap: 8,
        }}>
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {notice && (
        <div style={{
          marginTop: 14, padding: 12, borderRadius: 8, background: '#f0fdf4',
          color: '#15803d', fontSize: 13, display: 'flex', gap: 8,
        }}>
          <CheckCircle2 size={16} />
          {notice}
        </div>
      )}

      {report && (
        <div style={{ marginTop: 18 }}>
          <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap', marginBottom: 16 }}>
            {[
              ['Уже в порядке', report.counts.in_sync ?? 0, '#15803d'],
              ['Нужна версия', report.counts.needs_version ?? 0, '#2563eb'],
              ['Расхождения', report.counts.conflict ?? 0, '#b45309'],
              ['Без позиций', report.counts.empty ?? 0, '#64748b'],
            ].map(([label, value, color]) => (
              <div key={String(label)}>
                <div style={{ fontSize: 12, color: '#64748b' }}>{label}</div>
                <div style={{ fontSize: 22, fontWeight: 600, color: String(color) }}>
                  {value}
                </div>
              </div>
            ))}
          </div>

          {needsVersion.length > 0 && (
            <div style={cardStyle}>
              <b style={{ fontSize: 14 }}>Нужна рабочая версия</b>
              <p style={{ margin: '4px 0 10px', fontSize: 12, color: '#64748b' }}>
                Отметьте сметы, которые сейчас в работе на тендере, — их не тронем.
              </p>
              {needsVersion.map((entry) => (
                <label
                  key={entry.task_id}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0',
                    borderTop: '1px solid #f1f5f9', fontSize: 13, cursor: 'pointer',
                  }}
                >
                  <input
                    type="checkbox"
                    aria-label={`Не трогать: ${entry.task_name}`}
                    checked={untouched.has(entry.task_id)}
                    onChange={() => toggle(entry.task_id)}
                  />
                  <span style={{ flex: 1 }}>{entry.task_name}</span>
                  <span style={{ color: '#64748b' }}>
                    позиций: {entry.items_count} · {money(entry.items_total)}
                  </span>
                </label>
              ))}
              {/* Когда отмечены все сметы, делать нечего: кнопка, которая
                  ничего не меняет, выглядит как поломка. */}
              <button
                onClick={handleApply}
                disabled={busy || toProcess === 0}
                title={toProcess === 0 ? 'Все сметы отмечены как «не трогать»' : undefined}
                style={{
                  marginTop: 12, padding: '8px 16px', borderRadius: 8,
                  border: `1px solid ${toProcess === 0 ? '#cbd5e1' : '#2563eb'}`,
                  background: '#fff', color: toProcess === 0 ? '#94a3b8' : '#2563eb',
                  cursor: busy || toProcess === 0 ? 'default' : 'pointer', fontSize: 14,
                }}
              >
                <PlayCircle size={14} style={{ verticalAlign: -2, marginRight: 6 }} />
                Создать недостающие версии ({toProcess})
              </button>
            </div>
          )}

          {conflicts.length > 0 && (
            <div style={cardStyle}>
              <b style={{ fontSize: 14 }}>Расхождения — решать по одной</b>
              <p style={{ margin: '4px 0 10px', fontSize: 12, color: '#64748b' }}>
                Здесь расчёт и редактор показывают разные цифры. Выберите, чьи
                данные верны. Прежнее состояние сохранится в истории сметы.
              </p>
              {conflicts.map((entry) => (
                <div
                  key={entry.task_id}
                  style={{ padding: '10px 0', borderTop: '1px solid #f1f5f9' }}
                >
                  <div style={{ fontSize: 13, fontWeight: 600 }}>{entry.task_name}</div>
                  <div style={{ fontSize: 12, color: '#64748b', margin: '4px 0 8px' }}>
                    расходится позиций: {entry.diff_count} · итог расчёта{' '}
                    {money(entry.items_total)} · итог редактора{' '}
                    {money(entry.version_total)}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button
                      onClick={() => handleResolve(entry, 'items')}
                      disabled={busy}
                      style={{
                        padding: '6px 12px', borderRadius: 8, fontSize: 13,
                        border: '1px solid #b45309', background: '#fff',
                        color: '#b45309', cursor: busy ? 'default' : 'pointer',
                      }}
                    >
                      Взять из расчёта
                    </button>
                    <button
                      onClick={() => handleResolve(entry, 'version')}
                      disabled={busy}
                      style={{
                        padding: '6px 12px', borderRadius: 8, fontSize: 13,
                        border: '1px solid #cbd5e1', background: '#fff',
                        color: '#475569', cursor: busy ? 'default' : 'pointer',
                      }}
                    >
                      Оставить как в редакторе
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {needsVersion.length === 0 && conflicts.length === 0 && (
            <div style={{ ...cardStyle, color: '#15803d', fontSize: 13 }}>
              Все сметы уже переведены — делать ничего не нужно.
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default EstimateMigrationPanel;
