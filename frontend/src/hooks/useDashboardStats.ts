import { useState, useEffect, useCallback } from 'react';
import { getDashboardStats, DashboardStats } from '../api/dashboard';

const POLL_INTERVAL = 30_000;

export function useDashboardStats() {
  const [data, setData] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      const stats = await getDashboardStats();
      setData(stats);
      setError(null);
    } catch {
      setError('Ошибка загрузки данных');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
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
  }, [fetch]);

  return { data, loading, error, refetch: fetch };
}
