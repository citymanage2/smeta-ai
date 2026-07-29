/**
 * Tests for TaskStatus.tsx
 *
 * Bug: progress_message is not displayed during task processing.
 * The component only renders progressLog (accumulated history array)
 * but that array is empty on the first render — so nothing shows
 * even when task.progress_message is already set.
 *
 * Fix: render task.progress_message directly under the status badge.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// ── mocks ─────────────────────────────────────────────────────────────────

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

// notificationSound регистрирует глобальный click-листенер с AudioContext,
// который jsdom не поддерживает — мок убирает сайд-эффект при .click() в тестах.
vi.mock('../utils/notificationSound', () => ({
  playSuccess: vi.fn(),
  playError: vi.fn(),
}));

// ── helpers ───────────────────────────────────────────────────────────────

import { getTaskStatus, getTaskResults, TaskStatusResponse } from '../api/tasks';
import { TaskStatus } from '../types';
import TaskStatusPage from '../pages/TaskStatus';

function makeTaskResponse(overrides: Partial<TaskStatusResponse> = {}): TaskStatusResponse {
  return {
    id: 'aaaaaaaa-0000-0000-0000-000000000001',
    task_type: 'RESEARCH_PROJECT' as any,
    status: 'processing' as TaskStatus,
    progress_message: undefined,
    error_message: undefined,
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

// ── tests ─────────────────────────────────────────────────────────────────

describe('TaskStatus — progress_message display', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(getTaskResults).mockResolvedValue([]);
  });

  it('shows progress_message directly under the status badge when processing', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'processing', progress_message: 'Анализ проектной документации...' })
    );

    renderPage();

    // Must be rendered via a dedicated element, not just via progressLog accumulation
    const el = await screen.findByTestId('progress-message');
    expect(el).toBeInTheDocument();
    expect(el).toHaveTextContent('Анализ проектной документации...');
  });

  it('shows progress_message directly under the status badge when pending', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'pending', progress_message: 'Задача ожидает выполнения...' })
    );

    renderPage();

    const el = await screen.findByTestId('progress-message');
    expect(el).toHaveTextContent('Задача ожидает выполнения...');
  });

  it('does NOT render the progress-message element when progress_message is null', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'processing', progress_message: undefined })
    );

    renderPage();
    await screen.findByText('Обработка');  // wait for render
    expect(screen.queryByTestId('progress-message')).toBeNull();
  });

  it('does NOT render the progress-message element for completed tasks', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'completed', progress_message: 'Результаты сохранены' })
    );
    vi.mocked(getTaskResults).mockResolvedValue([]);

    renderPage();

    await screen.findByText('Завершено');
    expect(screen.queryByTestId('progress-message')).toBeNull();
  });
});

// ── Phase 1: resume button shows wherever a checkpoint exists ────────────────

describe('TaskStatus — resume button visibility (Phase 1)', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(getTaskResults).mockResolvedValue([]);
  });

  it('shows "Продолжить" for a failed CHECK_LIST_COMPLETENESS with a chunk checkpoint', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'CHECK_LIST_COMPLETENESS' as any,
        status: 'failed',
        error_message: 'Ошибка',
        progress_data: { chunks_done: 2, total_chunks: 5 } as any,
      })
    );

    renderPage();

    const btn = await screen.findByTestId('resume-button');
    expect(btn).toBeInTheDocument();
    expect(btn).toHaveTextContent('Продолжить');
  });

  it('shows "Продолжить" for a failed CHECK_PROJECT_COMPLETENESS with a chunk checkpoint', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'CHECK_PROJECT_COMPLETENESS' as any,
        status: 'failed',
        error_message: 'Ошибка',
        progress_data: { chunks_done: 1, total_chunks: 3 } as any,
      })
    );

    renderPage();

    expect(await screen.findByTestId('resume-button')).toBeInTheDocument();
  });

  it('still shows "Продолжить" for a failed ESTIMATE_FROM_LIST at pre_excel stage (regression)', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'ESTIMATE_FROM_LIST' as any,
        status: 'failed',
        error_message: 'Ошибка',
        progress_data: { _stage: 'pre_excel' } as any,
      })
    );

    renderPage();

    expect(await screen.findByTestId('resume-button')).toBeInTheDocument();
  });

  it('shows "Продолжить" for a failed ESTIMATE_FROM_LIST at claude_partial stage (Phase 2b)', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'ESTIMATE_FROM_LIST' as any,
        status: 'failed',
        error_message: 'Баланс API исчерпан',
        progress_data: { _stage: 'claude_partial', claude_results: { '0': {} } } as any,
      })
    );

    renderPage();

    expect(await screen.findByTestId('resume-button')).toBeInTheDocument();
  });

  it('shows "Продолжить" for a failed LIST_FROM_GRAND with a partial OCR checkpoint', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'LIST_FROM_GRAND' as any,
        status: 'failed',
        error_message: 'Задача прервана: сервер был перезапущен во время обработки.',
        progress_data: {
          ocr_pages_partial: [
            { page: 1, text: 'a', method: 'ocr' },
            { page: 2, text: 'b', method: 'ocr' },
            { page: 3, text: 'c', method: 'ocr' },
          ],
        } as any,
      })
    );

    renderPage();

    const btn = await screen.findByTestId('resume-button');
    expect(btn).toHaveTextContent('Продолжить');
    // сообщение с числом уже распознанных страниц
    expect(screen.getByText(/Распознано\s*3\s*стр/)).toBeInTheDocument();
  });

  it('shows "Продолжить" for a failed LIST_FROM_GRAND after OCR fully done (ocr_pages)', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'LIST_FROM_GRAND' as any,
        status: 'failed',
        error_message: 'Ошибка',
        progress_data: { ocr_pages: [{ page: 1, text: 'a', method: 'ocr' }] } as any,
      })
    );

    renderPage();

    expect(await screen.findByTestId('resume-button')).toBeInTheDocument();
  });

  it('shows only "Перезапустить" for a failed task without a checkpoint', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'LIST_FROM_PROJECT' as any,
        status: 'failed',
        error_message: 'Ошибка',
        progress_data: undefined,
      })
    );

    renderPage();

    await screen.findByText('Ошибка выполнения');
    expect(screen.queryByTestId('resume-button')).toBeNull();
    expect(screen.getByTestId('restart-button')).toBeInTheDocument();
  });
});

// ── Phase 5: paused status block + «Продолжить сейчас» ───────────────────────

describe('TaskStatus — paused status (Phase 5)', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(getTaskResults).mockResolvedValue([]);
  });

  it('renders the paused block with «Продолжить сейчас» for a paused task', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'ESTIMATE_FROM_LIST' as any,
        status: 'paused',
        error_message: 'Баланс API Anthropic исчерпан. Задача продолжится автоматически после пополнения счёта.',
        progress_data: { _stage: 'claude_partial' } as any,
      })
    );

    renderPage();

    const block = await screen.findByTestId('paused-block');
    expect(block).toBeInTheDocument();
    const btn = screen.getByTestId('resume-now-button');
    expect(btn).toHaveTextContent('Продолжить сейчас');
  });

  it('«Продолжить сейчас» calls resumeTask', async () => {
    const { resumeTask } = await import('../api/tasks');
    vi.mocked(resumeTask).mockResolvedValue({ task_id: 'x', status: 'pending' } as any);
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'ESTIMATE_FROM_LIST' as any,
        status: 'paused',
        error_message: 'Баланс API исчерпан',
        progress_data: { _stage: 'claude_partial' } as any,
      })
    );

    renderPage();

    const btn = await screen.findByTestId('resume-now-button');
    btn.click();
    expect(vi.mocked(resumeTask)).toHaveBeenCalledWith('aaaaaaaa-0000-0000-0000-000000000001');
  });

  it('shows «На паузе» status label for a paused task', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status: 'paused', progress_data: { _stage: 'pre_excel' } as any })
    );

    renderPage();

    expect(await screen.findByText('На паузе')).toBeInTheDocument();
  });
});

// Прод 29.07.2026: сборка результатов пачки падала с 403 (запрос уходил мимо
// посредника), задача вставала в failed с чекпоинтом batch_pending. Единственной
// кнопкой был перезапуск с начала — вторая оплата уже посчитанной пачки.
// План: plans/2026-07-29-batch-results-via-proxy.md, Фаза 2.
describe('TaskStatus — failed batch task with a paid batch', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(getTaskResults).mockResolvedValue([]);
  });

  function failedBatchTask() {
    return makeTaskResponse({
      task_type: 'ESTIMATE_FROM_LIST' as any,
      status: 'failed',
      error_message: "Ошибка сборки сметы из batch: Error code: 403 - {'type': 'forbidden'}",
      progress_data: { _stage: 'batch_pending', batch_id: 'msgbatch_y' } as any,
    });
  }

  it('offers «Продолжить» instead of a paid recalculation', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(failedBatchTask());

    renderPage();

    const btn = await screen.findByTestId('resume-batch-button');
    expect(btn).toHaveTextContent('забрать готовый расчёт');
    expect(screen.getByText(/уже выполнен и оплачен/)).toBeInTheDocument();
  });

  it('«Продолжить» calls resumeTask, not restartTask', async () => {
    const { resumeTask, restartTask } = await import('../api/tasks');
    vi.mocked(resumeTask).mockResolvedValue({ task_id: 'x', status: 'processing' } as any);
    vi.mocked(getTaskStatus).mockResolvedValue(failedBatchTask());

    renderPage();

    const btn = await screen.findByTestId('resume-batch-button');
    btn.click();
    expect(vi.mocked(resumeTask)).toHaveBeenCalledWith('aaaaaaaa-0000-0000-0000-000000000001');
    expect(vi.mocked(restartTask)).not.toHaveBeenCalled();
  });

  it('does not offer the batch resume without batch_id (nothing was paid for)', async () => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: 'ESTIMATE_FROM_LIST' as any,
        status: 'failed',
        error_message: 'Ошибка',
        progress_data: { _stage: 'batch_pending' } as any,
      })
    );

    renderPage();

    await screen.findByText(/Ошибка выполнения/i);
    expect(screen.queryByTestId('resume-batch-button')).toBeNull();
  });
});
