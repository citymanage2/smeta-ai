/**
 * Строка «Результат ≈ …» в карточке задачи.
 *
 * Менеджер держит эту страницу открытой, пока ждёт смету; таймер «сколько уже
 * идёт» не отвечает на его вопрос — можно ли обещать результат сегодня.
 *
 * План: plans/2026-07-30-eta-ocheredi-zadach.md, Фаза 5.
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

function makeTaskResponse(overrides: Partial<TaskStatusResponse> = {}): TaskStatusResponse {
  return {
    id: 'aaaaaaaa-0000-0000-0000-000000000001',
    task_type: 'ESTIMATE_FROM_LIST' as never,
    status: 'processing' as TaskStatus,
    estimation_status: 'unestimated',
    cost: null,
    project_id: null,
    created_at: new Date(Date.now() - 30 * 60 * 1000).toISOString(),
    updated_at: new Date().toISOString(),
    worker_heartbeat_age_s: 5,
    eta: {
      starts_in_s: 0,
      ready_in_s: 2400,
      ready_at: new Date(Date.now() + 2400_000).toISOString(),
      rough: false,
      finishing: false,
      units: 1220,
      unit_kind: 'items',
    },
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

describe('TaskStatus — прогноз готовности', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(getTaskResults).mockResolvedValue([]);
  });

  it('считающаяся задача показывает время результата', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(makeTaskResponse());

    renderPage();

    const el = await screen.findByTestId('task-eta');
    expect(el).toHaveTextContent(/через 40 мин/);
  });

  it('ожидающая задача показывает и время старта', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        status: 'pending',
        eta: {
          starts_in_s: 3600,
          ready_in_s: 7200,
          ready_at: new Date(Date.now() + 7200_000).toISOString(),
          rough: true,
          finishing: false,
          units: null,
          unit_kind: null,
        },
      })
    );

    renderPage();

    const el = await screen.findByTestId('task-eta');
    expect(el).toHaveTextContent('старт ≈ через 1 ч');
    expect(el).toHaveTextContent('оценка грубая');
  });

  it('расчётное время вышло — «завершается», без отрицательных чисел', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        eta: {
          starts_in_s: 0,
          ready_in_s: 60,
          ready_at: new Date(Date.now() + 60_000).toISOString(),
          rough: false,
          finishing: true,
          units: 1220,
          unit_kind: 'items',
        },
      })
    );

    renderPage();

    const el = await screen.findByTestId('task-eta');
    expect(el).toHaveTextContent('Результат завершается');
  });

  it('завершённая задача прогноз не показывает', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'completed', eta: null })
    );

    renderPage();

    await screen.findByText(/ID задачи/i);
    expect(screen.queryByTestId('task-eta')).not.toBeInTheDocument();
  });
});

/**
 * Место в очереди в карточке задачи: «меня возьмут третьей» отвечает на вопрос
 * ожидания точнее, чем минуты (те — оценка).
 *
 * План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 8.
 */
describe('TaskStatus — место в очереди', () => {
  it('ожидающая задача показывает позицию, старт и результат', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        status: 'pending' as TaskStatus,
        worker_heartbeat_age_s: null,
        eta: {
          starts_in_s: 1800,
          ready_in_s: 4200,
          ready_at: new Date(Date.now() + 4200_000).toISOString(),
          rough: false,
          finishing: false,
          units: 1220,
          unit_kind: 'items',
          queue_position: 3,
        },
      })
    );
    renderPage();

    expect(await screen.findByTestId('task-queue-position')).toHaveTextContent('3-я в очереди');
    const eta = screen.getByTestId('task-eta');
    expect(eta).toHaveTextContent('старт ≈ через 30 мин');
    expect(eta).toHaveTextContent('через 1 ч 10 мин');
  });

  it('считающаяся задача позицию не показывает', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(makeTaskResponse());
    renderPage();

    await screen.findByTestId('task-eta');
    expect(screen.queryByTestId('task-queue-position')).toBeNull();
  });
});
