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
    const timer = setInterval(fetch, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [fetch]);

  return { data, loading, error, refetch: fetch };
}
