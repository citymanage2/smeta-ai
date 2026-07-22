/**
 * TDD tests for three ProjectDetail.tsx bugs:
 *
 * Bug 1: Clicking task card should navigate to /task/{id}/status,
 *        not trigger task creation or do nothing.
 *
 * Bug 2: "Оптимизировать" button must check BOTH isEstimateType AND
 *        estimation_status === 'estimated'. Currently missing isEstimateType check.
 *
 * Bug 3: estimation_status badge must show text for 'optimizing' status.
 *        ESTIMATION_LABELS has stale key 'processing_optimization', missing 'optimizing'.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// ── mocks ────────────────────────────────────────────────────────────────────

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ projectId: 'proj-1' }),
  };
});

vi.mock('../api/projects', () => ({
  getProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  exportProject: vi.fn(),
  downloadSlotFile: vi.fn(),
  uploadFileToSlot: vi.fn(),
}));

vi.mock('../api/tasks', () => ({
  getTaskStatus: vi.fn(),
}));

vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({ isAdmin: false }),
}));

vi.mock('../components/OptimizeModal', () => ({
  default: () => null,
}));

vi.mock('../components/HistoryModal', () => ({
  default: () => null,
}));

vi.mock('../components/kanban/KanbanBoard', () => ({
  KanbanBoard: () => null,
}));

// ── helpers ──────────────────────────────────────────────────────────────────

import { getProject } from '../api/projects';
import { EstimationStatus } from '../types';
import ProjectDetailPage from '../pages/ProjectDetail';

const TASK_ID = 'aaaaaaaa-0000-0000-0000-000000000001';

function makeProject(taskOverrides: { estimation_status?: EstimationStatus; task_type?: string; id?: string } = {}) {
  return {
    id: 'proj-1',
    name: 'Тестовый проект',
    description: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    unestimated: 0,
    estimated: 1,
    optimized: 0,
    other: 0,
    total_cost: 100000,
    tasks: [
      {
        id: TASK_ID,
        task_type: 'ESTIMATE_FROM_LIST',
        status: 'completed',
        estimation_status: 'estimated' as EstimationStatus,
        cost: 100000,
        created_at: '2026-01-01T00:00:00Z',
        slot_files: { estimate: 'estimate.xlsx' },
        source_file_name: 'source.pdf',
        ...taskOverrides,
      },
    ],
  };
}

async function renderPage() {
  const utils = render(
    <MemoryRouter>
      <ProjectDetailPage />
    </MemoryRouter>
  );
  // Дефолтный вид — 'kanban'; строки задач рендерятся только в виде 'list'.
  fireEvent.click(await screen.findByText('Список'));
  return utils;
}

// ── tests ────────────────────────────────────────────────────────────────────

describe('ProjectDetail — Bug 1: task card click navigates to status page', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    vi.mocked(getProject).mockResolvedValue(makeProject());
  });

  it('clicking the task row navigates to /tasks/{id}/status', async () => {
    await renderPage();
    const row = await screen.findByText('Смета из перечня');
    fireEvent.click(row);
    expect(mockNavigate).toHaveBeenCalledWith(`/tasks/${TASK_ID}/status`);
  });

  it('does NOT navigate when task id is falsy (guard against catch-all→/task/create redirect)', async () => {
    vi.mocked(getProject).mockResolvedValue(makeProject({ id: '' }));
    await renderPage();
    const row = await screen.findByText('Смета из перечня');
    fireEvent.click(row);
    expect(mockNavigate).not.toHaveBeenCalledWith('/tasks//status');
    expect(mockNavigate).not.toHaveBeenCalledWith('/tasks/undefined/status');
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

describe('ProjectDetail — Bug 2: Optimize button condition', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('shows Optimize button for estimate task type with estimation_status estimated', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ task_type: 'ESTIMATE_FROM_LIST', estimation_status: 'estimated' })
    );
    await renderPage();
    expect(await screen.findByText('Оптимизировать')).toBeInTheDocument();
  });

  it('does NOT show Optimize button for ESTIMATE_OPTIMIZATION task even if estimation_status is estimated', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ task_type: 'ESTIMATE_OPTIMIZATION', estimation_status: 'estimated' })
    );
    await renderPage();
    await screen.findByText('Оптимизация сметы');  // wait for render
    // Wait briefly for async render then check button is absent
    await new Promise(r => setTimeout(r, 50));
    expect(screen.queryByText('Оптимизировать')).toBeNull();
  });

  it('does NOT show Optimize button when estimation_status is unestimated', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ task_type: 'ESTIMATE_FROM_LIST', estimation_status: 'unestimated' })
    );
    await renderPage();
    await screen.findByText('Смета из перечня');
    expect(screen.queryByText('Оптимизировать')).toBeNull();
  });
});

describe('ProjectDetail — Bug 3: estimation status badge', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('shows "Рассчитана" badge for estimated status', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ estimation_status: 'estimated' })
    );
    await renderPage();
    expect(await screen.findByText('Рассчитана')).toBeInTheDocument();
  });

  it('shows "Оптимизируется" badge for optimizing status', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ estimation_status: 'optimizing' })
    );
    await renderPage();
    expect(await screen.findByText('Оптимизируется')).toBeInTheDocument();
  });

  it('shows "Оптимизирована" badge for optimized status', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ estimation_status: 'optimized' })
    );
    await renderPage();
    expect(await screen.findByText('Оптимизирована')).toBeInTheDocument();
  });

  it('shows "Не рассчитана" badge for unestimated status', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ estimation_status: 'unestimated' })
    );
    await renderPage();
    expect(await screen.findByText('Не рассчитана')).toBeInTheDocument();
  });

  it('does NOT show badge for not_applicable status', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ task_type: 'LIST_FROM_GRAND', estimation_status: 'not_applicable' })
    );
    await renderPage();
    await screen.findByText('Перечень из Гранд-сметы');
    expect(screen.queryByText('Не рассчитана')).toBeNull();
    expect(screen.queryByText('Рассчитана')).toBeNull();
  });
});
