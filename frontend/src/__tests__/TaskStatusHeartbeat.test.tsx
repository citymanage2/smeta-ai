/**
 * Признак жизни обработчика в карточке задачи.
 *
 * Крутилка и растущий таймер идут одинаково у работающей и у мёртвой задачи —
 * по ним нельзя понять, ждать дальше или перезапускать. Карточка показывает
 * факт: когда обработчик последний раз подал сигнал (jobs.claimed_at на бэкенде).
 *
 * План: plans/2026-07-29-diagnostika-v-admin-panel.md, Фаза 5.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ taskId: 'aaaaaaaa-0000-0000-0000-000000000001' }),
  };
});

vi.mock('../api/tasks', () => ({
  getTaskStatus: vi.fn(),
  getTaskResults: vi.fn(),
  sendMessage: vi.fn(),
  cancelTask: vi.fn(),
  downloadResult: vi.fn(),
  resumeTask: vi.fn(),
  restartTask: vi.fn(),
}));

// Страница сначала спрашивает, есть ли у задачи карточка сметы: если есть —
// уходит на неё. Без мока тест ждал реального отказа сети, и под нагрузкой
// разметка не успевала появиться.
vi.mock('../api/documents', () => ({
  locateDocumentByTask: vi.fn().mockRejectedValue(new Error('нет карточки')),
}));

vi.mock('../api/projects', () => ({
  listProjects: vi.fn().mockResolvedValue([]),
  linkTaskToProject: vi.fn(),
}));

vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({ isAdmin: false, isAuthenticated: true }),
}));

vi.mock('../components/BatchProgressBar', () => ({
  BatchProgressBar: () => null,
}));

vi.mock('../utils/notificationSound', () => ({
  playSuccess: vi.fn(),
  playError: vi.fn(),
}));

import { getTaskStatus, getTaskResults, TaskStatusResponse } from '../api/tasks';
import { TaskStatus } from '../types';
import TaskStatusPage from '../pages/TaskStatus';

// Задача старше отсрочки HEARTBEAT_GRACE_S: таймер «сколько идёт» считается от
// created_at, и для проверки предупреждений задача должна быть уже не свежей.
const OLD_CREATED_AT = new Date(Date.now() - 30 * 60 * 1000).toISOString();

function makeTaskResponse(overrides: Partial<TaskStatusResponse> = {}): TaskStatusResponse {
  return {
    id: 'aaaaaaaa-0000-0000-0000-000000000001',
    task_type: 'RESEARCH_PROJECT' as never,
    status: 'processing' as TaskStatus,
    estimation_status: 'not_applicable',
    cost: null,
    project_id: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <TaskStatusPage />
    </MemoryRouter>
  );
}

describe('TaskStatus — признак жизни обработчика', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(getTaskResults).mockResolvedValue([]);
  });

  it('свежий сигнал → «Обработчик на связи», без тревожной плашки', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'processing', worker_heartbeat_age_s: 12 })
    );

    renderPage();

    const el = await screen.findByTestId('worker-alive');
    expect(el).toHaveTextContent('Обработчик на связи');
    expect(el).toHaveTextContent('12 сек. назад');
    expect(screen.queryByTestId('worker-stale')).not.toBeInTheDocument();
  });

  it('молчание дольше порога → плашка с кнопкой перезапуска', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'processing', worker_heartbeat_age_s: 600 })
    );

    renderPage();

    const el = await screen.findByTestId('worker-stale');
    expect(el).toHaveTextContent('Обработчик молчит');
    expect(el).toHaveTextContent('10 мин. назад');
    expect(screen.getByRole('button', { name: /Перезапустить/ })).toBeInTheDocument();
    expect(screen.queryByTestId('worker-alive')).not.toBeInTheDocument();
  });

  it('processing без сигнала вовсе → «Обработчик не отвечает»', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        status: 'processing',
        worker_heartbeat_age_s: null,
        // Старше отсрочки: иначе предупреждение справедливо промолчит.
        created_at: OLD_CREATED_AT,
      })
    );

    renderPage();

    const el = await screen.findByTestId('worker-stale');
    expect(el).toHaveTextContent('Обработчик не отвечает');
  });

  it('pending без сигнала → «ещё не взята в обработку», а не «не отвечает»', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        status: 'pending',
        worker_heartbeat_age_s: null,
        created_at: OLD_CREATED_AT,
      })
    );

    renderPage();

    const el = await screen.findByTestId('worker-stale');
    expect(el).toHaveTextContent('Задача ещё не взята в обработку');
    expect(el).not.toHaveTextContent('Обработчик не отвечает');
  });

  it('свежая задача без сигнала молчит — обработчик ещё не успел её взять', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        status: 'pending',
        worker_heartbeat_age_s: null,
        created_at: new Date().toISOString(),
      })
    );

    renderPage();

    await screen.findByText(/ID задачи/i);
    expect(screen.queryByTestId('worker-stale')).not.toBeInTheDocument();
    expect(screen.queryByTestId('worker-alive')).not.toBeInTheDocument();
  });

  it('batch-режим не считается зависанием — обработчика там нет по замыслу', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        status: 'processing',
        worker_heartbeat_age_s: null,
        created_at: OLD_CREATED_AT,
        progress_data: { _stage: 'batch_pending', batch_id: 'msgbatch_123' },
      })
    );

    renderPage();

    await screen.findByText(/ID задачи/i);
    expect(screen.queryByTestId('worker-stale')).not.toBeInTheDocument();
  });

  it('завершённая задача не показывает признак жизни вовсе', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'completed', worker_heartbeat_age_s: null })
    );

    renderPage();

    // Дожидаемся отрисовки карточки, затем проверяем отсутствие обоих блоков.
    await screen.findByText(/ID задачи/i);
    expect(screen.queryByTestId('worker-alive')).not.toBeInTheDocument();
    expect(screen.queryByTestId('worker-stale')).not.toBeInTheDocument();
  });
});
