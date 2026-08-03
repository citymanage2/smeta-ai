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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';

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
      only_order: false, same_totals: false,
      items_rows: 60, version_rows: 58,
      samples: [
        { name: 'Кладка стен',
          what: 'цена работы: расчёт 1 000,00, редактор 777,00',
          items: '4,00 м3, работа 1 000,00',
          version: '4,00 м3, работа 777,00' },
        { name: 'Штукатурка',
          what: 'строки нет в редакторе — она есть только в расчёте',
          items: '10,00 м2, работа 500,00', version: 'строки нет' },
      ],
    },
    {
      task_id: 't5', task_name: 'Гараж — смета', status: 'conflict',
      items_count: 200, version_count: 200, diff_count: 203,
      items_total: 9127176, version_total: 9127176,
      only_order: true, same_totals: true,
      items_rows: 200, version_rows: 200, samples: [],
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

    // Расхождений на экране несколько — смотрим карточку нужной сметы.
    const card = screen.getByText('Детсад — смета').parentElement!;
    const text = card.textContent?.replace(/\u00a0|\u202f/g, ' ') ?? '';
    expect(text).toContain('расходится позиций: 4');
    expect(text).toContain('1 800 000');
    expect(text).toContain('1 755 000');
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

    const card = screen.getByText('Детсад — смета').parentElement!;
    fireEvent.click(within(card).getByRole('button', { name: /взять из расч/i }));

    await waitFor(() =>
      expect(adminApi.resolveEstimateConflict).toHaveBeenCalledWith('t3', 'items'));
  });

  it('«оставить как в редакторе» тоже фиксируется', async () => {
    vi.mocked(adminApi.resolveEstimateConflict).mockResolvedValue({
      task_id: 't3', task_name: 'Детсад — смета', status: 'resolved',
      items_total: 1800000, version_total: 1755000,
    });
    await openPanel();

    const card = screen.getByText('Детсад — смета').parentElement!;
    fireEvent.click(
      within(card).getByRole('button', { name: /оставить как в редакторе/i }));

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

  it('видно, сколько строк с каждой стороны', async () => {
    await openPanel();

    // «60 против 58» сразу говорит, что состав строк разный.
    const card = screen.getByText('Детсад — смета').parentElement;
    expect(card).toHaveTextContent('60');
    expect(card).toHaveTextContent('58');
  });

  it('перестановка строк объяснена словами и не пугает', async () => {
    await openPanel();

    const card = screen.getByText('Гараж — смета').parentElement;
    expect(card).toHaveTextContent(/порядок/i);
    expect(card).toHaveTextContent(/совпада/i);
  });

  it('пример различия показывает обе величины', async () => {
    await openPanel();

    const card = screen.getByText('Детсад — смета').parentElement!;
    expect(within(card).getByText(/Кладка стен/)).toBeInTheDocument();
    expect(within(card).getByText(/расчёт: 4,00 м3, работа 1 000,00/))
      .toBeInTheDocument();
    expect(within(card).getByText(/редактор: 4,00 м3, работа 777,00/))
      .toBeInTheDocument();
  });

  it('в примере сказано, какое поле разошлось', async () => {
    // Две одинаковые с виду строки — самый бесполезный вид отчёта: различие
    // сидит там, куда человек не смотрит.
    await openPanel();

    const card = screen.getByText('Детсад — смета').parentElement!;
    expect(within(card).getByText(/цена работы: расчёт 1 000,00, редактор 777,00/))
      .toBeInTheDocument();
  });

  it('пропавшая строка названа словами, а не показана как изменённая', async () => {
    await openPanel();

    const card = screen.getByText('Детсад — смета').parentElement!;
    expect(within(card).getByText(/строки нет в редакторе/)).toBeInTheDocument();
  });

  it('когда деньги одинаковые, это сказано прямо', async () => {
    await openPanel();

    const card = screen.getByText('Гараж — смета').parentElement;
    expect(card).toHaveTextContent(/итоги совпадают/i);
  });

  it('ошибка сервера объясняется словами', async () => {
    vi.mocked(adminApi.getEstimateMigrationReport).mockRejectedValue(new Error('нет сети'));
    render(<EstimateMigrationPanel />);

    fireEvent.click(screen.getByRole('button', { name: /проверить/i }));

    expect(await screen.findByText(/не удалось/i)).toBeInTheDocument();
  });

  it('причина ошибки видна на экране — иначе её негде взять', async () => {
    // У пользователя нет доступа к логам сервера: если причина не показана,
    // «попробуйте ещё раз» — единственное, что он может сделать.
    vi.mocked(adminApi.getEstimateMigrationReport).mockRejectedValue({
      response: { status: 500, data: { detail: 'unsupported format string' } },
    });
    render(<EstimateMigrationPanel />);

    fireEvent.click(screen.getByRole('button', { name: /проверить/i }));

    const box = await screen.findByText(/не удалось получить отчёт/i);
    expect(box).toHaveTextContent(/500/);
    expect(box).toHaveTextContent(/unsupported format string/);
  });

  it('до проверки применять нечего', () => {
    render(<EstimateMigrationPanel />);

    expect(screen.queryByRole('button', { name: /создать недостающие версии/i }))
      .not.toBeInTheDocument();
  });
});
