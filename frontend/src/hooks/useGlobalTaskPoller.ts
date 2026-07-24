import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useNotificationStore } from '../stores/notificationStore';
import { getTaskStatus } from '../api/tasks';
import { notify } from '../utils/notify';

// Задачи, по которым уже показали тост о паузе — чтобы не спамить каждые 5 с.
// Задача остаётся в trackedTasks (авто-возобновится и завершится штатно).
const pausedNotified = new Set<string>();

const POLL_INTERVAL = 5000;

export function useGlobalTaskPoller(): void {
  const navigate = useNavigate();

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const checkOne = async (taskId: string, meta: { projectName: string; taskName: string }) => {
      if (window.location.pathname.startsWith(`/tasks/${taskId}`)) return;
      const { removeTask } = useNotificationStore.getState();
      try {
        const status = await getTaskStatus(taskId);

        if (status.status === 'completed') {
          notify('success', { taskId, projectName: meta.projectName, taskName: meta.taskName }, navigate);
          pausedNotified.delete(taskId);
          removeTask(taskId);
        } else if (status.status === 'failed') {
          notify(
            'error',
            {
              taskId,
              projectName: meta.projectName,
              taskName: meta.taskName,
              errorText: status.error_message ?? 'Неизвестная ошибка',
            },
            navigate,
          );
          pausedNotified.delete(taskId);
          removeTask(taskId);
        } else if (status.status === 'paused') {
          // Пауза (баланс API исчерпан) — не терминальный статус: задачу НЕ
          // снимаем с отслеживания, она возобновится автоматически. Тост —
          // один раз, чтобы не спамить каждый тик.
          if (!pausedNotified.has(taskId)) {
            pausedNotified.add(taskId);
            toast(`⏸ На паузе · ${meta.projectName} · ${meta.taskName}`, {
              description: 'Баланс API исчерпан. Задача продолжится автоматически после пополнения.',
              duration: 6000,
              action: {
                label: 'Открыть',
                onClick: () => navigate(`/tasks/${taskId}/status`),
              },
            });
          }
        } else {
          // Снова в работе (pending/processing) после паузы — сбрасываем флаг,
          // чтобы при повторной паузе показать тост ещё раз.
          pausedNotified.delete(taskId);
        }
      } catch (err) {
        console.error(`[TaskPoller] Ошибка при запросе задачи ${taskId}:`, err);
      }
    };

    const poll = async () => {
      // Пауза в фоне: свёрнутая вкладка не должна дёргать сервер.
      if (document.hidden) return;
      const { trackedTasks } = useNotificationStore.getState();
      // Параллельно, а не по одной последовательно: при N отслеживаемых задачах
      // тик занимает время одного запроса, а не суммы N.
      await Promise.allSettled(
        Array.from(trackedTasks).map(([taskId, meta]) => checkOne(taskId, meta)),
      );
    };

    // Self-scheduling: следующий тик планируется только после завершения текущего —
    // нет наложения запросов при медленном ответе.
    const tick = async () => {
      await poll();
      if (!cancelled) timer = setTimeout(tick, POLL_INTERVAL);
    };
    timer = setTimeout(tick, POLL_INTERVAL);

    // Немедленный опрос при возврате на вкладку — чтобы не ждать полный интервал.
    const onVisible = () => {
      if (!document.hidden) poll();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [navigate]);
}
