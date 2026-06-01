import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useNotificationStore } from '../stores/notificationStore';
import { getTaskStatus } from '../api/tasks';
import { notify } from '../utils/notify';

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
            removeTask(taskId);
          }
        } catch (err) {
          console.error(`[TaskPoller] Ошибка при запросе задачи ${taskId}:`, err);
        }
      }
    }, 5000);

    return () => clearInterval(id);
  }, [navigate]);
}
