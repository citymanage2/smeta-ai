/**
 * «Найти аналоги» — поиск более дешёвой замены через ИИ.
 *
 * Фаза 11 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`.
 *
 * Поиск платный, поэтому проверяется в первую очередь то, что защищает от
 * лишних трат и от испорченной сметы: подтверждение с честной оценкой до
 * запуска, возможность остановить прогон и то, что «Заменить» правит строку
 * через черновик — значит откатывается.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/documents', async () => {
  const actual = await vi.importActual<typeof import('../api/documents')>('../api/documents');
  return {
    ...actual,
    startAnalogs: vi.fn(),
    getAnalogsState: vi.fn(),
    cancelAnalogs: vi.fn(),
  };
});

import * as documentsApi from '../api/documents';
import AnalogsPanel, { safeSourceUrl } from '../components/editor/AnalogsPanel';
import FindAnalogs, { estimateAnalogsEffort } from '../components/editor/actions/FindAnalogs';
import { applyAnalogToRow } from '../components/editor/actions/analogsApply';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { GridRow } from '../components/editor/adapters/types';

const REF = { cardId: 'card-1', kind: 'estimate' as const };

const ROWS: GridRow[] = [
  { __key: 'r1', type: 'Работа', name: 'Кладка стен', unit: 'м3', qty: 10,
    price_work: 1000, price_material: null },
  { __key: 'r2', type: 'Материал', name: 'Кирпич', unit: 'шт', qty: 500,
    price_work: null, price_material: 25 },
  { __key: 'r3', type: 'Раздел', name: 'Отделка', unit: null, qty: null,
    price_work: null, price_material: null },
];

const DONE_STATE: documentsApi.AnalogsState = {
  run_id: 'run-1',
  status: 'done',
  processed: 2,
  total: 2,
  error: null,
  created_at: '2026-08-03T10:00:00Z',
  results: [
    {
      row_id: 'r1', name: 'Кладка стен', unit: 'м3', price: 1000,
      variants: [{
        name: 'Кладка из газобетонных блоков', unit: 'м3', price: 700,
        delta: 3000, reason: 'та же несущая способность', source: 'https://example.ru',
      }],
    },
    { row_id: 'r2', name: 'Кирпич', unit: 'шт', price: 25, variants: [] },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Оценка объёма — то, что человек видит до запуска
// ---------------------------------------------------------------------------

describe('оценка объёма', () => {
  it('растёт вместе с числом позиций', () => {
    expect(estimateAnalogsEffort(200).minutes)
      .toBeGreaterThan(estimateAnalogsEffort(5).minutes);
  });

  it('никогда не обещает ноль минут', () => {
    expect(estimateAnalogsEffort(1).minutes).toBeGreaterThanOrEqual(1);
  });
});

// ---------------------------------------------------------------------------
// Запуск
// ---------------------------------------------------------------------------

function renderFind(selected: string[], props: Partial<React.ComponentProps<typeof FindAnalogs>> = {}) {
  const onStarted = vi.fn();
  const onNotice = vi.fn();
  render(
    <FindAnalogs
      documentRef={REF}
      rows={ROWS}
      selectedKeys={new Set(selected)}
      rowKind={estimateAdapter.rowKind}
      busy={false}
      onStarted={onStarted}
      onNotice={onNotice}
      {...props}
    />,
  );
  return { onStarted, onNotice };
}

describe('запуск поиска', () => {
  it('без выделения кнопка недоступна', () => {
    renderFind([]);

    expect(screen.getByRole('button', { name: /найти аналоги/i })).toBeDisabled();
  });

  it('перед запуском показывает оценку объёма и предупреждает о плате', () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderFind(['r1', 'r2']);

    fireEvent.click(screen.getByRole('button', { name: /найти аналоги/i }));

    const message = confirmSpy.mock.calls[0][0] as string;
    expect(message).toContain('2');
    expect(message).toMatch(/мин/i);
    expect(message).toMatch(/интернет|плат|денег/i);
    confirmSpy.mockRestore();
  });

  it('отказ в подтверждении ничего не запускает', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderFind(['r1']);

    fireEvent.click(screen.getByRole('button', { name: /найти аналоги/i }));

    expect(documentsApi.startAnalogs).not.toHaveBeenCalled();
  });

  it('отправляет выделенные позиции с их ценами', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(documentsApi.startAnalogs).mockResolvedValue({
      run_id: 'run-1', status: 'queued', total: 2,
      estimate: { positions: 2, searches: 4, minutes: 1 },
    });
    renderFind(['r1', 'r2']);

    fireEvent.click(screen.getByRole('button', { name: /найти аналоги/i }));

    await waitFor(() => expect(documentsApi.startAnalogs).toHaveBeenCalledTimes(1));
    const [, payload] = vi.mocked(documentsApi.startAnalogs).mock.calls[0];
    expect(payload).toEqual([
      { row_id: 'r1', name: 'Кладка стен', unit: 'м3', qty: 10, price: 1000, kind: 'work' },
      { row_id: 'r2', name: 'Кирпич', unit: 'шт', qty: 500, price: 25, kind: 'material' },
    ]);
  });

  it('разделы на поиск не отправляются', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    vi.mocked(documentsApi.startAnalogs).mockResolvedValue({
      run_id: 'run-1', status: 'queued', total: 1,
      estimate: { positions: 1, searches: 2, minutes: 1 },
    });
    renderFind(['r1', 'r3']);

    fireEvent.click(screen.getByRole('button', { name: /найти аналоги/i }));

    await waitFor(() => expect(documentsApi.startAnalogs).toHaveBeenCalled());
    const [, payload] = vi.mocked(documentsApi.startAnalogs).mock.calls[0];
    expect(payload).toHaveLength(1);
  });

  it('идущий поиск не даёт запустить второй', () => {
    renderFind(['r1'], { busy: true });

    expect(screen.getByRole('button', { name: /найти аналоги/i })).toBeDisabled();
  });
});

// ---------------------------------------------------------------------------
// Панель результатов
// ---------------------------------------------------------------------------

function renderPanel(state: documentsApi.AnalogsState, onReplace = vi.fn()) {
  const onCancel = vi.fn();
  render(
    <AnalogsPanel state={state} onReplace={onReplace} onCancel={onCancel} onClose={() => {}} />,
  );
  return { onReplace, onCancel };
}

describe('панель результатов', () => {
  it('пока идёт поиск, показывает прогресс и даёт остановить', () => {
    const { onCancel } = renderPanel({
      ...DONE_STATE, status: 'running', processed: 1, total: 4, results: [],
    });

    expect(screen.getByText(/1 из 4/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /остановить/i }));
    expect(onCancel).toHaveBeenCalled();
  });

  it('показывает вариант с ценой, выгодой, обоснованием и источником', () => {
    renderPanel(DONE_STATE);

    expect(screen.getByText('Кладка из газобетонных блоков')).toBeInTheDocument();
    expect(screen.getByText(/700/)).toBeInTheDocument();
    expect(screen.getByText(/3\s?000/)).toBeInTheDocument();
    expect(screen.getByText(/та же несущая способность/)).toBeInTheDocument();
    // Адрес нормализован разбором URL — проверка протокола приводит его к
    // каноническому виду.
    expect(screen.getByRole('link', { name: /источник/i }))
      .toHaveAttribute('href', 'https://example.ru/');
  });

  it('«Заменить» отдаёт строку и выбранный вариант', () => {
    const { onReplace } = renderPanel(DONE_STATE);

    fireEvent.click(screen.getByRole('button', { name: /заменить/i }));

    expect(onReplace).toHaveBeenCalledWith('r1', DONE_STATE.results[0].variants[0]);
  });

  it('позиция без аналогов объясняется словами', () => {
    renderPanel(DONE_STATE);

    expect(screen.getByText(/аналогов не нашлось/i)).toBeInTheDocument();
  });

  it('опасная ссылка от ИИ не становится ссылкой', () => {
    // Источник приходит из ответа модели — это недоверенный текст.
    expect(safeSourceUrl('javascript:alert(1)')).toBeNull();
    expect(safeSourceUrl('data:text/html,<script>')).toBeNull();
    expect(safeSourceUrl('  ')).toBeNull();
    expect(safeSourceUrl('не ссылка вовсе')).toBeNull();
    expect(safeSourceUrl('https://example.ru/price')).toBe('https://example.ru/price');
  });

  it('вариант с опасной ссылкой показывается, но без перехода', () => {
    renderPanel({
      ...DONE_STATE,
      results: [{
        ...DONE_STATE.results[0],
        variants: [{ ...DONE_STATE.results[0].variants[0], source: 'javascript:alert(1)' }],
      }],
    });

    expect(screen.getByText('Кладка из газобетонных блоков')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: /источник/i })).not.toBeInTheDocument();
  });

  it('поломка показывается человеку', () => {
    renderPanel({
      ...DONE_STATE, status: 'failed', results: [],
      error: 'Поиск аналогов не удался: Claude недоступен',
    });

    expect(screen.getByText(/Claude недоступен/)).toBeInTheDocument();
  });

  it('остановленный поиск отмечен как остановленный', () => {
    renderPanel({ ...DONE_STATE, status: 'cancelled' });

    expect(screen.getByText(/остановлен/i)).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Замена строки вариантом
// ---------------------------------------------------------------------------

describe('замена позиции аналогом', () => {
  const VARIANT = {
    name: 'Кладка из газобетонных блоков', unit: 'м3', price: 700,
    delta: 3000, reason: 'та же несущая способность', source: 'https://example.ru',
  };

  it('подставляет наименование, единицу и цену работы', () => {
    const row = applyAnalogToRow(ROWS[0], VARIANT, null);

    expect(row.name).toBe('Кладка из газобетонных блоков');
    expect(row.unit).toBe('м3');
    expect(row.price_work).toBe(700);
    expect(row.cost_work).toBe(7000);
  });

  it('у материала меняет цену материалов, а не работ', () => {
    const row = applyAnalogToRow(ROWS[1], { ...VARIANT, price: 18 }, null);

    expect(row.price_material).toBe(18);
    expect(row.price_work).toBeFalsy();
  });

  it('при действующем коэффициенте цена аналога едет базовой', () => {
    const row = applyAnalogToRow(ROWS[0], VARIANT, { work: 1.05, material: 1, scope: 'all' });

    expect(row.__base_price_work).toBe(700);
    expect(row.price_work).toBe(735);
  });

  it('оставляет след, откуда взялась замена', () => {
    const row = applyAnalogToRow(ROWS[0], VARIANT, null);

    expect(String(row.notes)).toMatch(/аналог/i);
  });
});
