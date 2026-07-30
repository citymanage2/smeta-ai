/**
 * Свёрнутое левое меню раскрывается по наведению курсора и сворачивается
 * обратно, когда курсор уходит. Закреплённое кнопкой меню на наведение
 * не реагирует — оно статично.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, act, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

const mockNavigate = vi.fn();

vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useLocation: () => ({ pathname: '/task/create' }),
  };
});

vi.mock('../api/projects', () => ({
  listProjects: vi.fn(async () => []),
  createProject: vi.fn(),
  getProject: vi.fn(),
  getUnassignedTasks: vi.fn(async () => []),
  updateProject: vi.fn(),
}));

vi.mock('../api/tasks', () => ({
  updateTask: vi.fn(),
  softDeleteTask: vi.fn(),
}));

import ProjectsSidebar from '../components/ProjectsSidebar';

function renderSidebar(open: boolean) {
  const onToggle = vi.fn();
  const utils = render(
    <MemoryRouter>
      <ProjectsSidebar open={open} onToggle={onToggle} />
    </MemoryRouter>,
  );
  // Контейнер меню — единственный прямой потомок корня.
  const container = utils.container.firstElementChild as HTMLElement;
  return { ...utils, container, onToggle };
}

// Развёрнутое меню узнаётся по кнопке «Новая задача» — в узкой полосе её нет.
const expandedMarker = () => screen.queryByText('Новая задача');

describe('Свёрнутое меню: раскрытие по наведению', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    mockNavigate.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('свёрнутое меню раскрывается при наведении курсора', async () => {
    const { container } = renderSidebar(false);

    expect(expandedMarker()).toBeNull();

    fireEvent.mouseEnter(container);

    await waitFor(() => expect(expandedMarker()).not.toBeNull());
  });

  it('сворачивается обратно, когда курсор уходит', async () => {
    const { container } = renderSidebar(false);

    fireEvent.mouseEnter(container);
    await waitFor(() => expect(expandedMarker()).not.toBeNull());

    fireEvent.mouseLeave(container);
    // Пауза перед сворачиванием — до её истечения меню ещё открыто.
    expect(expandedMarker()).not.toBeNull();

    act(() => { vi.advanceTimersByTime(300); });

    await waitFor(() => expect(expandedMarker()).toBeNull());
  });

  it('не сворачивается, если открыта форма создания проекта', async () => {
    const { container } = renderSidebar(false);

    fireEvent.mouseEnter(container);
    await waitFor(() => expect(expandedMarker()).not.toBeNull());

    fireEvent.click(screen.getByTitle('Создать новый проект'));
    await waitFor(() => expect(screen.queryByPlaceholderText('Название *')).not.toBeNull());

    fireEvent.mouseLeave(container);
    act(() => { vi.advanceTimersByTime(300); });

    expect(expandedMarker()).not.toBeNull();
  });

  it('во временно раскрытом меню нижняя кнопка закрепляет меню', async () => {
    const { container, onToggle } = renderSidebar(false);

    fireEvent.mouseEnter(container);
    await waitFor(() => expect(expandedMarker()).not.toBeNull());

    fireEvent.click(screen.getByText('Закрепить меню'));
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});

describe('Закреплённое меню статично', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('не сворачивается, когда курсор уходит', async () => {
    const { container } = renderSidebar(true);

    await waitFor(() => expect(expandedMarker()).not.toBeNull());

    fireEvent.mouseLeave(container);
    act(() => { vi.advanceTimersByTime(300); });

    expect(expandedMarker()).not.toBeNull();
    expect(screen.queryByText('Свернуть меню')).not.toBeNull();
  });
});
