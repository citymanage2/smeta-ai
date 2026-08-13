import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronUp, Play, RotateCw } from 'lucide-react';
import { TaskStatusResponse, getTaskStatus, restartTask, resumeTask } from '../../api/tasks';
import { formatApiDetail } from '../../utils/formatError';
import { StageErrorNote } from '../kanban/StageErrorNote';
import { describeEta } from '../../utils/eta';
import { LumaSpin } from '../ui/LumaSpin';
import './StageProcessingPanel.css';

/**
 * Ход обработки этапа — то, ради чего раньше существовала отдельная страница
 * задачи: сообщения обработчика, время, стоимость, ошибка и кнопки перезапуска.
 *
 * Живёт прямо в карточке сметы, рядом с этапом, к которому относится, а не на
 * отдельном экране: у одной сметы четыре этапа, и переход «туда-обратно» ради
 * лога был основным источником путаницы «где я нахожусь».
 */

interface Props {
  taskId: string;
  /** Позвать, когда задача сменила состояние — чтобы карточка перечитала файлы. */
  onChanged?: () => void;
}

const POLL_MS = 3000;
const ACTIVE = new Set(['pending', 'processing']);

function formatMoney(cost: number): string {
  return new Intl.NumberFormat('ru-RU', {
    style: 'currency', currency: 'RUB', maximumFractionDigits: 0,
  }).format(cost);
}

function formatElapsed(startedAt: string | null | undefined): string | null {
  if (!startedAt) return null;
  const seconds = Math.floor((Date.now() - new Date(startedAt).getTime()) / 1000);
  if (seconds < 0) return null;
  if (seconds < 60) return `${seconds} сек.`;
  return `${Math.floor(seconds / 60)} мин. ${seconds % 60} сек.`;
}

export const StageProcessingPanel: React.FC<Props> = ({ taskId, onChanged }) => {
  const [task, setTask] = useState<TaskStatusResponse | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [busy, setBusy] = useState<'restart' | 'resume' | null>(null);
  const [actionError, setActionError] = useState('');
  const [tick, setTick] = useState(0);
  const lastStatusRef = useRef<string | null>(null);

  // Колбэк держим в ref: иначе вызывающий с обычной стрелкой в пропсах менял бы
  // идентичность fetch на каждый рендер, и опрос перезапускался бы бесконечно.
  const onChangedRef = useRef(onChanged);
  useEffect(() => { onChangedRef.current = onChanged; });

  const fetch = useCallback(async () => {
    try {
      const data = await getTaskStatus(taskId);
      setTask(data);
      if (lastStatusRef.current && lastStatusRef.current !== data.status) {
        onChangedRef.current?.();
      }
      lastStatusRef.current = data.status;
    } catch {
      // Молча: панель — дополнение к карточке, а не её условие.
    }
  }, [taskId]);

  useEffect(() => {
    lastStatusRef.current = null;
    fetch();
  }, [fetch]);

  const isActive = task ? ACTIVE.has(task.status) : false;
  const isFailed = task?.status === 'failed' || task?.status === 'cancelled';
  const isPaused = task?.status === 'paused';

  // Пока задача идёт — обновляемся; завершённая задача не опрашивается вовсе.
  useEffect(() => {
    if (!isActive) return;
    const timer = setInterval(fetch, POLL_MS);
    return () => clearInterval(timer);
  }, [isActive, fetch]);

  // Счётчик времени тикает отдельно от опроса — иначе цифра стоит по 3 секунды.
  useEffect(() => {
    if (!isActive) return;
    const timer = setInterval(() => setTick((v) => v + 1), 1000);
    return () => clearInterval(timer);
  }, [isActive]);

  // Предупреждение обработчика («⚠ ИИ не вернул позиции…») — про неполный
  // результат успешно завершённой задачи. Свёрнутая панель прячет его так же
  // надёжно, как раньше прятался сам пропуск, поэтому разворачиваем.
  const warning = (task?.progress_log ?? []).find((line) => line.startsWith('⚠')) ?? '';

  // Ошибку разворачиваем сразу: за ней и приходят.
  useEffect(() => {
    if (isFailed || isPaused || warning) setExpanded(true);
  }, [isFailed, isPaused, warning]);

  if (!task) return null;

  const elapsed = isActive ? formatElapsed(task.started_at) : null;
  const eta = describeEta(task.eta, task.status);
  const log = task.progress_log ?? [];

  const runAction = async (kind: 'restart' | 'resume') => {
    setBusy(kind);
    setActionError('');
    try {
      if (kind === 'restart') await restartTask(taskId);
      else await resumeTask(taskId);
      await fetch();
      onChangedRef.current?.();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setActionError(formatApiDetail(detail, kind === 'restart'
        ? 'Не удалось перезапустить задачу.'
        : 'Не удалось возобновить задачу.'));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={`spp${isFailed ? ' spp-failed' : ''}`} data-testid="stage-processing">
      <button className="spp-head" onClick={() => setExpanded((v) => !v)}>
        {isActive && <LumaSpin size="sm" color="#d97706" />}
        {isFailed && <AlertTriangle size={14} color="#dc2626" />}

        <span className="spp-title">
          {isActive ? (task.progress_message || 'В очереди…')
            : isFailed ? 'Ошибка обработки'
            : isPaused ? 'Обработка на паузе'
            : 'Ход обработки'}
        </span>

        {elapsed && <span className="spp-meta" data-tick={tick}>{elapsed}</span>}
        {eta && <span className="spp-meta" title={eta.hint}>Готово {eta.ready}</span>}
        {task.cost != null && task.cost > 0 && (
          <span className="spp-meta">{formatMoney(task.cost)}</span>
        )}

        {expanded ? <ChevronUp size={14} color="#94a3b8" /> : <ChevronDown size={14} color="#94a3b8" />}
      </button>

      {expanded && (
        <div className="spp-body">
          {/* Причина — тем же блоком, что и в списке смет: понятный текст плюс
              технический оригинал под «Подробности», иначе переслать
              разработчику нечего. */}
          <StageErrorNote message={task.error_message} />


          {log.length > 0 ? (
            <ol className="spp-log">
              {log.map((line, index) => (
                <li key={index} className={index === log.length - 1 ? 'spp-log-last' : undefined}>
                  {line}
                </li>
              ))}
            </ol>
          ) : (
            <div className="spp-empty">Сообщений обработчика пока нет</div>
          )}

          {actionError && <div className="spp-error">{actionError}</div>}

          <div className="spp-actions">
            {isPaused && (
              <button
                className="spp-btn spp-btn-primary"
                onClick={() => runAction('resume')}
                disabled={busy !== null}
              >
                <Play size={13} />
                {busy === 'resume' ? 'Возобновляю…' : 'Возобновить'}
              </button>
            )}
            {!isActive && (
              <button
                className="spp-btn"
                onClick={() => runAction('restart')}
                disabled={busy !== null}
              >
                <RotateCw size={13} />
                {busy === 'restart' ? 'Запускаю…' : 'Перезапустить'}
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default StageProcessingPanel;
