import { toast } from 'sonner';
import { NavigateFunction } from 'react-router-dom';
import { playSuccess, playError } from './notificationSound';
import { shortTaskError } from './formatError';

export interface TaskInfo {
  taskId: string;
  projectName: string;
  taskName: string;
  errorText?: string;
}

let notificationPermissionRequested = false;

async function requestNotificationPermission(): Promise<void> {
  if (notificationPermissionRequested) return;
  notificationPermissionRequested = true;
  if ('Notification' in window && Notification.permission === 'default') {
    await Notification.requestPermission();
  }
}

function sendBrowserNotification(title: string, body: string): void {
  if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
    new Notification(title, { body });
  }
}

export function notify(
  type: 'success' | 'error',
  taskInfo: TaskInfo,
  navigate?: NavigateFunction,
): void {
  if (type === 'success') {
    playSuccess();
    const label = `✓ Завершено · ${taskInfo.projectName} · ${taskInfo.taskName}`;
    toast.success(label, {
      duration: 6000,
      action: navigate
        ? { label: 'Открыть', onClick: () => navigate(`/tasks/${taskInfo.taskId}/status`) }
        : undefined,
    });
    requestNotificationPermission().then(() => {
      sendBrowserNotification('✓ Задача завершена', `${taskInfo.projectName} · ${taskInfo.taskName}`);
    });
  } else {
    playError();
    // Не сырой текст исключения: «'unit'» в уведомлении ничего не сообщает.
    const errorText = shortTaskError(taskInfo.errorText);
    const label = `✗ Ошибка: ${errorText} · ${taskInfo.taskName}`;
    toast.error(label, {
      duration: 6000,
      action: navigate
        ? { label: 'Открыть', onClick: () => navigate(`/tasks/${taskInfo.taskId}/status`) }
        : undefined,
    });
    requestNotificationPermission().then(() => {
      sendBrowserNotification('✗ Ошибка задачи', `${taskInfo.taskName}: ${errorText}`);
    });
  }
}
