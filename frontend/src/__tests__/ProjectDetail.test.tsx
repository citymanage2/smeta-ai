/**
 * TDD tests for three ProjectDetail.tsx bugs:
 *
 * Bug 1: Clicking task card should navigate to /task/{id}/status,
 *        not trigger task creation or do nothing.
 *
 * Bug 2: "Оптимизировать" button must check BOTH isEstimateType AND
 *        estimation_status === 'estimated'. Currently missing isEstimateType check.
 *
 * Bug 3 → Фаза 6 (КП-6): двойной статус схлопнут в единое представление.
 *        Вместо отдельного цветного estimation-бейджа строка задачи показывает
 *        состояние стадии (Готово/Идёт/Ошибка) + тонкую бизнес-пометку
 *        (рассчитана / оптимизирована / идёт оптимизация). Проверяем, что
 *        бизнес-факт не потерян, но выражен как пометка, а не как второй бейдж.
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

// SmetaList — дефолтный вид проекта; тянет kanban-стор и поллит workflow-cards.
// Для этих тестов сырых задач он не нужен — мокаем, чтобы не было сетевых вызовов.
vi.mock('../components/SmetaList', () => ({
  SmetaList: () => null,
}));

// notificationSound регистрирует глобальный click-листенер с AudioContext,
// которого нет в jsdom — при .click() в тестах он бросает ReferenceError.
// Мок убирает сайд-эффект.
vi.mock('../utils/notificationSound', () => ({
  playSuccess: vi.fn(),
  playError: vi.fn(),
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
  // Дефолтный вид — 'smeta' (список смет); сырые задачи рендерятся в виде 'Задачи'.
  fireEvent.click(await screen.findByText('Задачи'));
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

describe('ProjectDetail — Bug 3 → Фаза 6: единый статус (состояние стадии + бизнес-пометка)', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
  });

  it('показывает состояние «Готово» и пометку «рассчитана» для estimated', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ estimation_status: 'estimated' })  // status по умолчанию 'completed'
    );
    await renderPage();
    expect(await screen.findByText('Готово')).toBeInTheDocument();
    expect(await screen.findByText(/рассчитана/)).toBeInTheDocument();
  });

  it('показывает пометку «идёт оптимизация» для optimizing (смысл optimizing не потерян)', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ estimation_status: 'optimizing' })
    );
    await renderPage();
    expect(await screen.findByText(/идёт оптимизация/)).toBeInTheDocument();
  });

  it('показывает пометку «оптимизирована» для optimized', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ estimation_status: 'optimized' })
    );
    await renderPage();
    expect(await screen.findByText(/оптимизирована/)).toBeInTheDocument();
  });

  it('для unestimated показывает состояние стадии без бизнес-пометки', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ estimation_status: 'unestimated' })
    );
    await renderPage();
    // состояние стадии показано (задача completed → «Готово»)…
    expect(await screen.findByText('Готово')).toBeInTheDocument();
    // …а старого красного бейджа «Не рассчитана» больше нет
    expect(screen.queryByText('Не рассчитана')).toBeNull();
  });

  it('не показывает бизнес-пометку для not_applicable, но показывает состояние стадии', async () => {
    vi.mocked(getProject).mockResolvedValue(
      makeProject({ task_type: 'LIST_FROM_GRAND', estimation_status: 'not_applicable' })
    );
    await renderPage();
    await screen.findByText('Перечень из Гранд-сметы');
    expect(screen.queryByText(/рассчитана/)).toBeNull();
    expect(screen.queryByText(/оптимизирована/)).toBeNull();
    expect(screen.getByText('Готово')).toBeInTheDocument();
  });
});
