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
