import { useEffect, useState } from 'react';

import { getKpCounters } from '../api/kpRequests';

/**
 * Счётчик новых запросов КП своей роли — для шапки отдела производства
 * (план plans/2026-09-14-zapros-kp.md, фаза 5, критерий 13).
 *
 * Почты и Telegram нет (решение пользователя 14.09.2026): новый запрос человек
 * узнаёт по цифре в шапке, поэтому она перечитывается опросом раз в 30 секунд
 * при видимой вкладке и сразу — после «Взять в работу» (`refreshKpCounters`).
 *
 * Продажам счётчик новых не нужен (сервер отдаёт им 0) — хук с `enabled=false`
 * в сеть не ходит.
 */

const POLL_MS = 30_000;
const REFRESH_EVENT = 'kp-counters-refresh';

/** Перечитать счётчик сейчас — после действия, которое его меняет. */
export function refreshKpCounters(): void {
  window.dispatchEvent(new Event(REFRESH_EVENT));
}

export function useKpCounters(enabled: boolean): number {
  const [count, setCount] = useState(0);

  useEffect(() => {
    if (!enabled) {
      setCount(0);
      return undefined;
    }
    let alive = true;
    const load = async () => {
      try {
        const data = await getKpCounters();
        if (alive) setCount(Math.max(0, Number(data?.new) || 0));
      } catch {
        // Молча: счётчик — подсказка, а не повод ломать шапку.
      }
    };
    load();
    const timer = window.setInterval(() => { if (!document.hidden) load(); }, POLL_MS);
    const onRefresh = () => { load(); };
    const onVisible = () => { if (!document.hidden) load(); };
    window.addEventListener(REFRESH_EVENT, onRefresh);
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      alive = false;
      window.clearInterval(timer);
      window.removeEventListener(REFRESH_EVENT, onRefresh);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [enabled]);

  return count;
}
