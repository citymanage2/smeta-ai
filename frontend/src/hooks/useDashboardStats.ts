import { useState, useEffect, useCallback } from 'react';
import { getDashboardStats, DashboardStats } from '../api/dashboard';

const POLL_INTERVAL = 30_000;

// enabled=false → хук не шлёт запрос (не-менеджер получил бы 403 на /dashboard/stats).
export function useDashboardStats(enabled = true) {
  const [data, setData] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    if (!enabled) return;
    try {
      const stats = await getDashboardStats();
      setData(stats);
      setError(null);
    } catch {
      setError('Ошибка загрузки данных');
    } finally {
      setLoading(false);
    }
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    fetch();
    // Пауза в фоне: свёрнутая вкладка не льёт запрос каждые 30 с.
    const timer = setInterval(() => {
      if (!document.hidden) fetch();
    }, POLL_INTERVAL);
    // При возврате на вкладку — сразу обновить, не дожидаясь интервала.
    const onVisible = () => {
      if (!document.hidden) fetch();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [fetch, enabled]);

  return { data, loading, error, refetch: fetch };
}
