/**
 * Одна страница на смету (Фаза 3).
 *
 * Проверяем ровно то, ради чего страницы объединялись: старая ссылка на задачу
 * приводит на нужный этап сметы, ход обработки виден рядом с этапом и сам
 * раскрывается на ошибке, а чат-уточнение из интерфейса убран.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockNavigate = vi.fn();

const TASK_ID = 'task-77';

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ taskId: 'task-77' }),
  };
});

vi.mock('../api/documents', async () => {
  const actual = await vi.importActual<typeof import('../api/documents')>('../api/documents');
  return { ...actual, locateDocumentByTask: vi.fn() };
});

vi.mock('../api/tasks', () => ({
  getTaskStatus: vi.fn(),
  getTaskResults: vi.fn().mockResolvedValue([]),
  restartTask: vi.fn().mockResolvedValue({}),
  resumeTask: vi.fn().mockResolvedValue({}),
  cancelTask: vi.fn(),
  downloadResult: vi.fn(),
  downloadInputFile: vi.fn(),
  updateTask: vi.fn(),
  patchEstimateItems: vi.fn(),
  repriceEstimateItem: vi.fn(),
  fixEmptyPrices: vi.fn(),
}));

vi.mock('../api/projects', () => ({
  linkTaskToProject: vi.fn(),
  listProjects: vi.fn().mockResolvedValue([]),
  downloadSlotFile: vi.fn(),
}));

import * as documentsApi from '../api/documents';
import * as tasksApi from '../api/tasks';
import TaskStatusPage from '../pages/TaskStatus';
import StageProcessingPanel from '../components/card/StageProcessingPanel';

function task(overrides: Partial<tasksApi.TaskStatusResponse> = {}): tasksApi.TaskStatusResponse {
  return {
    id: TASK_ID,
    status: 'completed',
    task_type: 'LIST_FROM_GRAND',
    estimation_status: 'not_applicable',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    progress_log: ['Разбираю файл', 'Готово'],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(tasksApi.getTaskStatus).mockResolvedValue(task());
});

describe('старая ссылка на задачу', () => {
  it('открывает страницу сметы на этапе этой задачи', async () => {
    vi.mocked(documentsApi.locateDocumentByTask).mockResolvedValue({
      project_id: 'proj-1', card_id: 'card-9', kind: 'completeness',
    });

    render(<MemoryRouter initialEntries={[`/tasks/${TASK_ID}/status`]}><TaskStatusPage /></MemoryRouter>);

    await waitFor(() => {
      expect(mockNavigate).toHaveBeenCalledWith(
        '/projects/proj-1/cards/card-9?stage=completeness',
        { replace: true },
      );
    });
  });

  it('задача вне сметы остаётся на прежней странице', async () => {
    vi.mocked(documentsApi.locateDocumentByTask).mockRejectedValue({
      response: { status: 404 },
    });

    render(<MemoryRouter initialEntries={[`/tasks/${TASK_ID}/status`]}><TaskStatusPage /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getAllByText(/Перечень из Гранд-сметы/).length).toBeGreaterThan(0);
    });
    expect(mockNavigate).not.toHaveBeenCalledWith(
      expect.stringContaining('/cards/'), expect.anything(),
    );
  });

  it('чат-уточнение убран из интерфейса', async () => {
    vi.mocked(documentsApi.locateDocumentByTask).mockRejectedValue({
      response: { status: 404 },
    });

    render(<MemoryRouter initialEntries={[`/tasks/${TASK_ID}/status`]}><TaskStatusPage /></MemoryRouter>);

    await waitFor(() => {
      expect(screen.getAllByText(/Перечень из Гранд-сметы/).length).toBeGreaterThan(0);
    });
    expect(screen.queryByText('Уточнить задачу')).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/уточнение/i)).not.toBeInTheDocument();
  });
});

describe('ход обработки рядом с этапом', () => {
  it('свёрнут, пока всё идёт нормально', async () => {
    render(<StageProcessingPanel taskId={TASK_ID} />);

    await waitFor(() => {
      expect(screen.getByText('Ход обработки')).toBeInTheDocument();
    });
    expect(screen.queryByText('Разбираю файл')).not.toBeInTheDocument();
  });

  it('на ошибке раскрывается сам и показывает причину', async () => {
    vi.mocked(tasksApi.getTaskStatus).mockResolvedValue(task({
      status: 'failed',
      error_message: 'Не удалось разобрать файл',
    }));

    render(<StageProcessingPanel taskId={TASK_ID} />);

    await waitFor(() => {
      expect(screen.getByText('Ошибка обработки')).toBeInTheDocument();
    });
    expect(screen.getByText(/Не удалось разобрать файл/)).toBeInTheDocument();
    expect(screen.getByText('Разбираю файл')).toBeInTheDocument();
    expect(screen.getByText('Перезапустить')).toBeInTheDocument();
  });

  it('задача на паузе предлагает возобновить', async () => {
    vi.mocked(tasksApi.getTaskStatus).mockResolvedValue(task({ status: 'paused' }));

    render(<StageProcessingPanel taskId={TASK_ID} />);

    await waitFor(() => {
      expect(screen.getByText('Обработка на паузе')).toBeInTheDocument();
    });
    expect(screen.getByText('Возобновить')).toBeInTheDocument();
  });

  it('стоимость обработки показывается рядом с этапом', async () => {
    vi.mocked(tasksApi.getTaskStatus).mockResolvedValue(task({ cost: 812 }));

    render(<StageProcessingPanel taskId={TASK_ID} />);

    await waitFor(() => {
      expect(screen.getByText(/812/)).toBeInTheDocument();
    });
  });
});
