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
