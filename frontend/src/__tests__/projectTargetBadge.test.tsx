/**
 * Цель по объекту на карточке проекта и в списке проектов.
 *
 * План: `plans/2026-09-01-celi-optimizacii.md`, Фаза 6.
 *
 * Цель задаётся в сводной, а смотрят на неё чаще оттуда, где видна сумма
 * проекта. Поэтому цель и отклонение показаны рядом с суммой — и ровно по той
 * же формуле, что в бланке (`utils/targets`).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return { ...actual, useNavigate: () => vi.fn(), useParams: () => ({ projectId: 'proj-1' }) };
});

vi.mock('../api/projects', () => ({
  getProject: vi.fn(),
  updateProject: vi.fn(),
  deleteProject: vi.fn(),
  exportProject: vi.fn(),
  downloadSlotFile: vi.fn(),
  uploadFileToSlot: vi.fn(),
  listProjects: vi.fn(),
  createProject: vi.fn(),
  archiveProject: vi.fn(),
  reassignProjectOwner: vi.fn(),
}));
vi.mock('../api/tasks', () => ({ getTaskStatus: vi.fn() }));
vi.mock('../api/adminUsers', () => ({ listAssignable: vi.fn().mockResolvedValue([]) }));
vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({ isAdmin: false, isManager: false }),
}));
vi.mock('../components/OptimizeModal', () => ({ default: () => null }));
vi.mock('../components/HistoryModal', () => ({ default: () => null }));
vi.mock('../components/kanban/KanbanBoard', () => ({ KanbanBoard: () => null }));
vi.mock('../components/SmetaList', () => ({ SmetaList: () => null }));
vi.mock('../utils/notificationSound', () => ({ playSuccess: vi.fn(), playError: vi.fn() }));

import { getProject, listProjects } from '../api/projects';
import ProjectDetailPage from '../pages/ProjectDetail';
import ProjectsPage from '../pages/Projects';

/** Текст приходит с неразрывными пробелами — сравниваем по-человечески. */
const text = (needle: string) => (content: string) =>
  content.replace(/ /g, ' ').includes(needle);

const PROJECT = {
  id: 'proj-1',
  name: 'Объект',
  description: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  unestimated: 0,
  estimated: 1,
  optimized: 0,
  other: 0,
  total_cost: 300000,
  summary_total: 300000,
  has_summary: true,
  tasks: [],
};

describe('цель по объекту на карточке проекта', () => {
  beforeEach(() => vi.clearAllMocks());

  it('показывает цель и превышение красным', async () => {
    vi.mocked(getProject).mockResolvedValue({ ...PROJECT, summary_target_total: 250000 } as never);
    render(<MemoryRouter><ProjectDetailPage /></MemoryRouter>);

    expect(await screen.findByText('Цель:')).toBeInTheDocument();
    const deviation = await screen.findByText(text('+50 000 ₽'));
    expect(deviation).toHaveStyle({ color: 'rgb(220, 38, 38)' });
    expect(deviation.textContent!.replace(/\u00A0/g, ' ')).toContain('+20%');
  });

  it('экономия показана зелёным', async () => {
    vi.mocked(getProject).mockResolvedValue({ ...PROJECT, summary_target_total: 400000 } as never);
    render(<MemoryRouter><ProjectDetailPage /></MemoryRouter>);

    const deviation = await screen.findByText(text('-100 000 ₽'));
    expect(deviation).toHaveStyle({ color: 'rgb(5, 150, 105)' });
  });

  it('пока итог сводной не сохранён, показывает цель без отклонения', async () => {
    // Итог 0 — сводную ещё не открывали. Отклонение от нуля выглядело бы как
    // экономия на всю цель, поэтому его нет вовсе.
    vi.mocked(getProject).mockResolvedValue(
      { ...PROJECT, summary_total: 0, summary_target_total: 250000 } as never,
    );
    render(<MemoryRouter><ProjectDetailPage /></MemoryRouter>);

    expect(await screen.findByText('Цель:')).toBeInTheDocument();
    expect(screen.queryByText(text(' ₽ · '))).toBeNull();
    expect(screen.queryByText(text('-250 000 ₽'))).toBeNull();
  });

  it('без цели карточка выглядит как раньше', async () => {
    vi.mocked(getProject).mockResolvedValue(PROJECT as never);
    render(<MemoryRouter><ProjectDetailPage /></MemoryRouter>);

    expect(await screen.findByText('Сводная сформирована')).toBeInTheDocument();
    expect(screen.queryByText('Цель:')).toBeNull();
  });
});

describe('цель по объекту в списке проектов', () => {
  beforeEach(() => vi.clearAllMocks());

  it('строка цели стоит под суммой проекта', async () => {
    vi.mocked(listProjects).mockResolvedValue([
      { ...PROJECT, summary_target_total: 250000, task_type_counts: {}, total_tasks: 0 },
    ] as never);
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>);

    const target = await screen.findByText(text('Цель 250'));
    expect(target.textContent!.replace(/\u00A0/g, ' ')).toContain('+50 000 ₽');
  });

  it('без цели в списке ничего не появляется', async () => {
    vi.mocked(listProjects).mockResolvedValue([
      { ...PROJECT, task_type_counts: {}, total_tasks: 0 },
    ] as never);
    render(<MemoryRouter><ProjectsPage /></MemoryRouter>);

    expect(await screen.findByText('Объект')).toBeInTheDocument();
    expect(screen.queryByText(text('Цель '))).toBeNull();
  });
});
