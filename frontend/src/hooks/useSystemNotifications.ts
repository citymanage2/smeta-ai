import { useEffect } from 'react';
import { toast } from 'sonner';
import {
  getSystemNotifications,
  KIND_BALANCE_RESTORED,
  SystemNotification,
} from '../api/notifications';
import { playSuccess } from '../utils/notificationSound';

// Событие такого рода случается раз в недели — 30 секунд с запасом достаточно,
// а поллер задач (5 с) не хочется утяжелять.
const POLL_INTERVAL = 30000;

const CURSOR_KEY = 'systemEventCursor';

function readCursor(): number | null {
  const raw = localStorage.getItem(CURSOR_KEY);
  if (raw === null) return null;
  const parsed = Number(raw);
  return Number.isFinite(parsed) ? parsed : null;
}

function taskNames(event: SystemNotification): string {
  const names = event.tasks.map((t) => t.name).filter((n): n is string => Boolean(n));
  if (names.length === 0) return '';
  const head = names.slice(0, 3).join(', ');
  return names.length > 3 ? `${head} и ещё ${names.length - 3}` : head;
}

function showBalanceRestored(event: SystemNotification): void {
  playSuccess();
  const names = taskNames(event);
  const description = names
    ? `Возобновлены задачи: ${event.resumed_count} — ${names}`
    : `Возобновлены задачи: ${event.resumed_count}`;
  toast.success('✓ Баланс API пополнен', { description, duration: 10000 });
  if ('Notification' in window && Notification.permission === 'granted' && document.hidden) {
    new Notification('✓ Баланс API пополнен', { body: description });
  }
}

/**
 * Уведомление о восстановлении баланса API.
 *
 * Задачи на паузе возобновляются воркером молча, и по UI нельзя было отличить
 * «пополнение дошло» от «поллер не работает». Событие живёт в БД (воркер и web —
 * разные процессы), а вкладка спрашивает «что нового после курсора». Курсор в
 * localStorage, а не в памяти: пауза длится часами, и к моменту восстановления
 * страница почти наверняка перезагружена.
 */
export function useSystemNotifications(): void {
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async () => {
      // Свёрнутая вкладка не дёргает сервер.
      if (document.hidden) return;
      const cursor = readCursor();
      try {
        const data = await getSystemNotifications(cursor ?? 0);
        if (cancelled) return;
        // Первый заход: истории событий у вкладки нет — молча запоминаем позицию,
        // чтобы не вываливать пачку старых уведомлений при входе в систему.
        if (cursor === null) {
          localStorage.setItem(CURSOR_KEY, String(data.cursor));
          return;
        }
        // Курсор двигаем ДО показа: если toast бросит, событие не зациклится.
        if (data.cursor > cursor) {
          localStorage.setItem(CURSOR_KEY, String(data.cursor));
        }
        data.events
          .filter((e) => e.kind === KIND_BALANCE_RESTORED)
          .forEach(showBalanceRestored);
      } catch (err) {
        // Сеть/401 не должны ронять приложение и мешать поллеру задач.
        console.error('[SystemNotifications] Ошибка при запросе событий:', err);
      }
    };

    // Self-scheduling: следующий тик — только после завершения текущего.
    const tick = async () => {
      await poll();
      if (!cancelled) timer = setTimeout(tick, POLL_INTERVAL);
    };
    timer = setTimeout(tick, POLL_INTERVAL);
    poll();

    const onVisible = () => {
      if (!document.hidden) poll();
    };
    document.addEventListener('visibilitychange', onVisible);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, []);
}
