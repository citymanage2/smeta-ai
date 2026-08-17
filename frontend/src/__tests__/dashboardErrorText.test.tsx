import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import DashboardErrors from '../components/dashboard/DashboardErrors';
import { FailedTaskGroup } from '../api/dashboard';

vi.mock('../api/tasks', () => ({ resumeTask: vi.fn().mockResolvedValue({}) }));

// Прод 13–14.08.2026: журнал печатал error_message как есть, мимо
// formatTaskError, и четыре падения подряд выглядели как «'unit'».
// План: plans/2026-08-18-ponyatnyy-tekst-oshibki.md.

const NOW = new Date().toISOString();

function group(overrides: Partial<FailedTaskGroup> = {}): FailedTaskGroup {
  const pattern = overrides.pattern ?? "'unit'";
  return {
    pattern,
    task_type: 'ESTIMATE_FROM_LIST',
    count: 1,
    last_failed_at: NOW,
    tasks: [
      {
        id: 'task-1',
        task_type: 'ESTIMATE_FROM_LIST',
        error_message: pattern,
        created_at: NOW,
        error_pattern: pattern,
      },
    ],
    ...overrides,
  };
}

describe('Журнал ошибок — текст причины', () => {
  it('заголовок группы объясняет ошибку, а не показывает repr исключения', () => {
    render(<DashboardErrors groups={[group()]} onResume={() => {}} />);

    expect(screen.getByText(/в данных задачи нет поля «единица измерения»/)).toBeInTheDocument();
    expect(screen.queryByText("'unit'")).toBeNull();
  });

  it('технический оригинал не теряется — он под «Подробности»', () => {
    render(<DashboardErrors groups={[group()]} onResume={() => {}} />);

    fireEvent.click(screen.getByText(/в данных задачи нет поля/));
    fireEvent.click(screen.getByText('Подробности'));

    expect(screen.getByText("'unit'")).toBeInTheDocument();
  });

  it('разные технические тексты с одной причиной — одна строка журнала', () => {
    render(
      <DashboardErrors
        groups={[
          group({ pattern: "'unit'", count: 3 }),
          group({
            pattern: "KeyError: 'unit'",
            count: 1,
            tasks: [
              {
                id: 'task-2',
                task_type: 'ESTIMATE_FROM_LIST',
                error_message: "KeyError: 'unit'",
                created_at: NOW,
                error_pattern: "KeyError: 'unit'",
              },
            ],
          }),
        ]}
        onResume={() => {}}
      />
    );

    expect(screen.getAllByText(/в данных задачи нет поля «единица измерения»/)).toHaveLength(1);
    expect(screen.getByText('×4')).toBeInTheDocument();
  });

  it('разные причины остаются разными строками', () => {
    render(
      <DashboardErrors
        groups={[group(), group({ pattern: 'MemoryError' })]}
        onResume={() => {}}
      />
    );

    expect(screen.getByText(/в данных задачи нет поля/)).toBeInTheDocument();
    expect(screen.getByText(/Не хватило памяти/)).toBeInTheDocument();
  });
});
