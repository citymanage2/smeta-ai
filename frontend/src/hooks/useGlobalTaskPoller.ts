import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { useNotificationStore } from '../stores/notificationStore';
import { getTaskStatus } from '../api/tasks';
import { notify } from '../utils/notify';

// Задачи, по которым уже показали тост о паузе — чтобы не спамить каждые 5 с.
// Задача остаётся в trackedTasks (авто-возобновится и завершится штатно).
const pausedNotified = new Set<string>();

export function useGlobalTaskPoller(): void {
  const navigate = useNavigate();

  useEffect(() => {
    const id = setInterval(async () => {
      const { trackedTasks, removeTask } = useNotificationStore.getState();

      for (const [taskId, meta] of trackedTasks) {
        if (window.location.pathname.startsWith(`/tasks/${taskId}`)) continue;

        try {
          const status = await getTaskStatus(taskId);

          if (status.status === 'completed') {
            notify(
              'success',
              { taskId, projectName: meta.projectName, taskName: meta.taskName },
              navigate,
            );
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
      }
    }, 5000);

    return () => clearInterval(id);
  }, [navigate]);
}
