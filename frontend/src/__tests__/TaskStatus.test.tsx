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
import { numbersIn } from './screenQueries';

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

  it.each([
    { status: 'processing' as TaskStatus, message: 'Анализ проектной документации...' },
    { status: 'pending' as TaskStatus, message: 'Задача ожидает выполнения...' },
  ])('shows progress_message directly under the status badge when $status', async ({ status, message }) => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({ status, progress_message: message })
    );

    renderPage();

    // Must be rendered via a dedicated element, not just via progressLog accumulation
    const el = await screen.findByTestId('progress-message');
    expect(el).toHaveTextContent(message);
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

  it.each([
    { name: 'CHECK_LIST_COMPLETENESS, chunk checkpoint', task_type: 'CHECK_LIST_COMPLETENESS', progress_data: { chunks_done: 2, total_chunks: 5 } },
    { name: 'CHECK_PROJECT_COMPLETENESS, chunk checkpoint', task_type: 'CHECK_PROJECT_COMPLETENESS', progress_data: { chunks_done: 1, total_chunks: 3 } },
    { name: 'ESTIMATE_FROM_LIST, pre_excel stage (regression)', task_type: 'ESTIMATE_FROM_LIST', progress_data: { _stage: 'pre_excel' } },
    { name: 'ESTIMATE_FROM_LIST, claude_partial stage (Phase 2b)', task_type: 'ESTIMATE_FROM_LIST', progress_data: { _stage: 'claude_partial', claude_results: { '0': {} } } },
    { name: 'LIST_FROM_GRAND, partial OCR checkpoint', task_type: 'LIST_FROM_GRAND', progress_data: { ocr_pages_partial: [{ page: 1, text: 'a', method: 'ocr' }] } },
    { name: 'LIST_FROM_GRAND, OCR fully done (ocr_pages)', task_type: 'LIST_FROM_GRAND', progress_data: { ocr_pages: [{ page: 1, text: 'a', method: 'ocr' }] } },
  ])('offers resume for a failed task: $name', async ({ task_type, progress_data }) => {
    vi.mocked(getTaskStatus).mockResolvedValue(
      makeTaskResponse({
        task_type: task_type as any,
        status: 'failed',
        error_message: 'Ошибка',
        progress_data: progress_data as any,
      })
    );

    renderPage();

    expect(await screen.findByTestId('resume-button')).toBeInTheDocument();
  });

  it('partial OCR checkpoint tells how many pages are already recognized', async () => {
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

    await screen.findByTestId('resume-button');
    expect(numbersIn(screen.getByText(/Распознано/).textContent)).toEqual([3]);
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
