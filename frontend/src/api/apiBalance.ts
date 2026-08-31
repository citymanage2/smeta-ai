import apiClient from './client';

/** Отметка «в Console на дату D на счету было $X» — точка отсчёта остатка. */
export interface BalanceMark {
  id: number;
  balance_usd: number;
  measured_on: string;
  note: string | null;
  created_by: string | null;
  created_at: string;
}

/**
 * Снимок остатка денег на Claude API.
 *
 * `remaining_usd = null` — отметки нет, считать не от чего: показываем не ноль,
 * а «неизвестно». Ноль означал бы «денег нет», а это разные вещи.
 */
export interface ApiBalance {
  mark_usd: number | null;
  mark_on: string | null;
  /** Траты закрытых дней по официальному отчёту Anthropic. */
  official_usd: number;
  /** Траты сегодняшнего дня по собственному журналу вызовов. */
  live_usd: number;
  spent_usd: number;
  remaining_usd: number | null;
  /** По какой день включительно траты подтверждены Anthropic. */
  official_through: string | null;
  synced_at: string | null;
  /** Подключён ли админ-ключ: без него сверки с Anthropic нет вовсе. */
  official_enabled: boolean;
  avg_daily_usd: number;
  days_left: number | null;
  avg_estimate_usd: number | null;
  estimates_left: number | null;
  level: 'ok' | 'warn' | 'alarm' | 'unknown';
  marks: BalanceMark[];
  /**
   * Чем ответил Anthropic на последнюю сверку по кнопке. Приходит только с
   * `/sync`: «не сработало» без текста ответа выглядит одинаково при
   * неподходящем ключе, закрытом на прокси пути и личной организации.
   */
  sync_error?: string | null;
}

export async function fetchApiBalance(): Promise<ApiBalance> {
  const { data } = await apiClient.get<ApiBalance>('/api-balance');
  return data;
}

export async function createBalanceMark(
  balanceUsd: number,
  measuredOn?: string,
  note?: string,
): Promise<ApiBalance> {
  const { data } = await apiClient.post<ApiBalance>('/api-balance/marks', {
    balance_usd: balanceUsd,
    measured_on: measuredOn,
    note: note || undefined,
  });
  return data;
}

export async function deleteBalanceMark(id: number): Promise<ApiBalance> {
  const { data } = await apiClient.delete<ApiBalance>(`/api-balance/marks/${id}`);
  return data;
}

export async function syncApiBalance(): Promise<ApiBalance> {
  const { data } = await apiClient.post<ApiBalance>('/api-balance/sync');
  return data;
}
