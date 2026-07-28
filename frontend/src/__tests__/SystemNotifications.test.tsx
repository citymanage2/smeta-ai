/**
 * useSystemNotifications — уведомление «баланс API пополнен».
 *
 * Контракт (spec: specs/2026-07-28-balance-restored-notification.md):
 * - AC10: новое событие → toast с числом и названиями задач;
 * - AC11: первый заход (нет курсора) → тостов нет, курсор выставлен молча;
 * - AC12: то же событие не показывается дважды;
 * - AC13: скрытая вкладка не опрашивает сервер;
 * - AC14: ошибка запроса не роняет приложение.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';

const toastSuccess = vi.fn();
vi.mock('sonner', () => ({
  toast: { success: (...args: unknown[]) => toastSuccess(...args) },
}));

vi.mock('../utils/notificationSound', () => ({
  playSuccess: vi.fn(),
  playError: vi.fn(),
}));

vi.mock('../api/notifications', async () => {
  const actual = await vi.importActual<typeof import('../api/notifications')>(
    '../api/notifications',
  );
  return { ...actual, getSystemNotifications: vi.fn() };
});

import { getSystemNotifications } from '../api/notifications';
import { useSystemNotifications } from '../hooks/useSystemNotifications';

const CURSOR_KEY = 'systemEventCursor';

function balanceEvent(id: number, tasks: { id: string; name: string }[]) {
  return {
    id,
    kind: 'balance_restored',
    created_at: '2026-07-28T10:00:00Z',
    resumed_count: tasks.length,
    tasks,
  };
}

describe('useSystemNotifications', () => {
  beforeEach(() => {
    localStorage.clear();
    toastSuccess.mockClear();
    vi.mocked(getSystemNotifications).mockReset();
    Object.defineProperty(document, 'hidden', { value: false, configurable: true });
  });

  afterEach(() => {
    localStorage.clear();
  });

  it('AC11: первый заход — курсор выставляется молча, без тостов', async () => {
    vi.mocked(getSystemNotifications).mockResolvedValue({
      cursor: 7,
      events: [balanceEvent(7, [{ id: 't1', name: 'Смета А' }])],
    });

    renderHook(() => useSystemNotifications());

    await waitFor(() => expect(localStorage.getItem(CURSOR_KEY)).toBe('7'));
    expect(toastSuccess).not.toHaveBeenCalled();
  });

  it('AC10: новое событие показывает toast с числом и названиями', async () => {
    localStorage.setItem(CURSOR_KEY, '5');
    vi.mocked(getSystemNotifications).mockResolvedValue({
      cursor: 6,
      events: [
        balanceEvent(6, [
          { id: 't1', name: 'Смета А' },
          { id: 't2', name: 'Смета Б' },
        ]),
      ],
    });

    renderHook(() => useSystemNotifications());

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    const [title, opts] = toastSuccess.mock.calls[0] as [string, { description: string }];
    expect(title).toContain('Баланс API пополнен');
    expect(opts.description).toContain('Возобновлены задачи: 2');
    expect(opts.description).toContain('Смета А');
    expect(opts.description).toContain('Смета Б');
    expect(localStorage.getItem(CURSOR_KEY)).toBe('6');
  });

  it('AC10: длинный список названий сворачивается до трёх', async () => {
    localStorage.setItem(CURSOR_KEY, '1');
    vi.mocked(getSystemNotifications).mockResolvedValue({
      cursor: 2,
      events: [
        balanceEvent(
          2,
          ['А', 'Б', 'В', 'Г', 'Д'].map((n, i) => ({ id: `t${i}`, name: `Смета ${n}` })),
        ),
      ],
    });

    renderHook(() => useSystemNotifications());

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    const [, opts] = toastSuccess.mock.calls[0] as [string, { description: string }];
    expect(opts.description).toContain('и ещё 2');
    expect(opts.description).not.toContain('Смета Д');
  });

  it('AC12: курсор сдвигается — повторный опрос не показывает то же событие', async () => {
    localStorage.setItem(CURSOR_KEY, '5');
    vi.mocked(getSystemNotifications).mockResolvedValue({
      cursor: 6,
      events: [balanceEvent(6, [{ id: 't1', name: 'Смета А' }])],
    });

    renderHook(() => useSystemNotifications());

    await waitFor(() => expect(toastSuccess).toHaveBeenCalledTimes(1));
    // Следующий тик спрашивает уже от нового курсора — сервер вернёт пусто.
    expect(vi.mocked(getSystemNotifications).mock.calls[0][0]).toBe(5);
    expect(localStorage.getItem(CURSOR_KEY)).toBe('6');
  });

  it('AC12: событие без названий задач всё равно показывает количество', async () => {
    localStorage.setItem(CURSOR_KEY, '1');
    vi.mocked(getSystemNotifications).mockResolvedValue({
      cursor: 2,
      events: [{ ...balanceEvent(2, []), resumed_count: 3 }],
    });

    renderHook(() => useSystemNotifications());

    await waitFor(() => expect(toastSuccess).toHaveBeenCalled());
    const [, opts] = toastSuccess.mock.calls[0] as [string, { description: string }];
    expect(opts.description).toBe('Возобновлены задачи: 3');
  });

  it('AC13: скрытая вкладка не опрашивает сервер', async () => {
    Object.defineProperty(document, 'hidden', { value: true, configurable: true });
    vi.mocked(getSystemNotifications).mockResolvedValue({ cursor: 0, events: [] });

    renderHook(() => useSystemNotifications());
    await new Promise((r) => setTimeout(r, 20));

    expect(getSystemNotifications).not.toHaveBeenCalled();
  });

  it('AC14: ошибка запроса не ломает хук и не двигает курсор', async () => {
    localStorage.setItem(CURSOR_KEY, '4');
    vi.mocked(getSystemNotifications).mockRejectedValue(new Error('network'));

    renderHook(() => useSystemNotifications());

    await waitFor(() => expect(getSystemNotifications).toHaveBeenCalled());
    expect(toastSuccess).not.toHaveBeenCalled();
    expect(localStorage.getItem(CURSOR_KEY)).toBe('4');
  });

  it('игнорирует события чужого вида', async () => {
    localStorage.setItem(CURSOR_KEY, '1');
    vi.mocked(getSystemNotifications).mockResolvedValue({
      cursor: 2,
      events: [{ ...balanceEvent(2, [{ id: 't1', name: 'Смета А' }]), kind: 'something_else' }],
    });

    renderHook(() => useSystemNotifications());

    await waitFor(() => expect(localStorage.getItem(CURSOR_KEY)).toBe('2'));
    expect(toastSuccess).not.toHaveBeenCalled();
  });
});
