/**
 * Перевод смет на единый источник правды — из админки.
 *
 * План: `plans/2026-08-03-migraciya-smet-iz-adminki.md`.
 *
 * Операция разовая и необратимая, поэтому проверяется прежде всего то, что
 * защищает от случайной потери данных: сначала отчёт, активные тендеры можно
 * не трогать, а расхождения разбираются по одной смете с показом обоих итогов.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/admin', () => ({
  getEstimateMigrationReport: vi.fn(),
  applyEstimateMigration: vi.fn(),
  resolveEstimateConflict: vi.fn(),
}));

import * as adminApi from '../api/admin';
import EstimateMigrationPanel from '../components/admin/EstimateMigrationPanel';

const REPORT: adminApi.MigrationReport = {
  applied: false,
  counts: { needs_version: 2, in_sync: 5, conflict: 1, empty: 1 },
  labels: {},
  entries: [
    {
      task_id: 't1', task_name: 'ЖК Северный — смета', status: 'needs_version',
      items_count: 120, version_count: 0, diff_count: 0,
      items_total: 4500000, version_total: 0,
    },
    {
      task_id: 't2', task_name: 'Школа №7 — смета', status: 'needs_version',
      items_count: 80, version_count: 0, diff_count: 0,
      items_total: 2200000, version_total: 0,
    },
    {
      task_id: 't3', task_name: 'Детсад — смета', status: 'conflict',
      items_count: 60, version_count: 60, diff_count: 4,
      items_total: 1800000, version_total: 1755000,
    },
    {
      task_id: 't4', task_name: 'Склад — смета', status: 'in_sync',
      items_count: 30, version_count: 30, diff_count: 0,
      items_total: 900000, version_total: 900000,
    },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(adminApi.getEstimateMigrationReport).mockResolvedValue(REPORT);
});

async function openPanel() {
  render(<EstimateMigrationPanel />);
  fireEvent.click(screen.getByRole('button', { name: /проверить/i }));
  await screen.findByText(/Детсад/);
}

describe('перевод смет из админки', () => {
  it('показывает сводку по результатам проверки', async () => {
    await openPanel();

    // Рядом с подписью стоит её число: «Уже в порядке — 5», «Расхождения — 1».
    const inSync = screen.getByText('Уже в порядке').parentElement;
    expect(inSync).toHaveTextContent('5');
    const conflicts = screen.getByText('Расхождения').parentElement;
    expect(conflicts).toHaveTextContent('1');
  });

  it('перечисляет сметы, которым нужна рабочая версия', async () => {
    await openPanel();

    expect(screen.getByText(/ЖК Северный/)).toBeInTheDocument();
    expect(screen.getByText(/Школа №7/)).toBeInTheDocument();
  });

  it('расхождение показывает оба итога и число расходящихся позиций', async () => {
    await openPanel();

    // Оба итога и число расхождений — в одной строке под названием сметы.
    const line = screen.getByText(/расходится позиций/i);
    expect(line).toHaveTextContent('4');
    expect(line.textContent?.replace(/ | /g, ' ')).toContain('1 800 000');
    expect(line.textContent?.replace(/ | /g, ' ')).toContain('1 755 000');
  });

  it('отмеченные «не трогать» уходят в исключения', async () => {
    vi.mocked(adminApi.applyEstimateMigration).mockResolvedValue({
      ...REPORT, applied: true,
    });
    await openPanel();

    fireEvent.click(screen.getByLabelText('Не трогать: ЖК Северный — смета'));
    fireEvent.click(screen.getByRole('button', { name: /создать недостающие версии/i }));

    await waitFor(() => expect(adminApi.applyEstimateMigration).toHaveBeenCalled());
    expect(adminApi.applyEstimateMigration).toHaveBeenCalledWith(['t1']);
  });

  it('без отметок исключений нет', async () => {
    vi.mocked(adminApi.applyEstimateMigration).mockResolvedValue({
      ...REPORT, applied: true,
    });
    await openPanel();

    fireEvent.click(screen.getByRole('button', { name: /создать недостающие версии/i }));

    await waitFor(() => expect(adminApi.applyEstimateMigration).toHaveBeenCalledWith([]));
  });

  it('«взять из расчёта» отправляет конкретную смету', async () => {
    vi.mocked(adminApi.resolveEstimateConflict).mockResolvedValue({
      task_id: 't3', task_name: 'Детсад — смета', status: 'resolved',
      items_total: 1800000, version_total: 1755000,
    });
    await openPanel();

    fireEvent.click(screen.getByRole('button', { name: /взять из расч/i }));

    await waitFor(() =>
      expect(adminApi.resolveEstimateConflict).toHaveBeenCalledWith('t3', 'items'));
  });

  it('«оставить как в редакторе» тоже фиксируется', async () => {
    vi.mocked(adminApi.resolveEstimateConflict).mockResolvedValue({
      task_id: 't3', task_name: 'Детсад — смета', status: 'resolved',
      items_total: 1800000, version_total: 1755000,
    });
    await openPanel();

    fireEvent.click(screen.getByRole('button', { name: /оставить как в редакторе/i }));

    await waitFor(() =>
      expect(adminApi.resolveEstimateConflict).toHaveBeenCalledWith('t3', 'version'));
  });

  it('после применения отчёт перечитывается — на экране свежие данные', async () => {
    vi.mocked(adminApi.applyEstimateMigration).mockResolvedValue({
      ...REPORT, applied: true,
    });
    await openPanel();

    fireEvent.click(screen.getByRole('button', { name: /создать недостающие версии/i }));

    await waitFor(() =>
      expect(adminApi.getEstimateMigrationReport).toHaveBeenCalledTimes(2));
  });

  it('когда отмечены все сметы, применять нечего', async () => {
    await openPanel();

    fireEvent.click(screen.getByLabelText('Не трогать: ЖК Северный — смета'));
    fireEvent.click(screen.getByLabelText('Не трогать: Школа №7 — смета'));

    expect(screen.getByRole('button', { name: /создать недостающие версии/i }))
      .toBeDisabled();
  });

  it('ошибка сервера объясняется словами', async () => {
    vi.mocked(adminApi.getEstimateMigrationReport).mockRejectedValue(new Error('нет сети'));
    render(<EstimateMigrationPanel />);

    fireEvent.click(screen.getByRole('button', { name: /проверить/i }));

    expect(await screen.findByText(/не удалось/i)).toBeInTheDocument();
  });

  it('до проверки применять нечего', () => {
    render(<EstimateMigrationPanel />);

    expect(screen.queryByRole('button', { name: /создать недостающие версии/i }))
      .not.toBeInTheDocument();
  });
});
