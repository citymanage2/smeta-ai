import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';

vi.mock('../api/documents', async () => {
  const actual = await vi.importActual<typeof import('../api/documents')>('../api/documents');
  return {
    ...actual,
    getDocumentMeta: vi.fn(),
    getDocumentRows: vi.fn(),
    saveDraft: vi.fn().mockResolvedValue(undefined),
    sendHeartbeat: vi.fn().mockResolvedValue(null),
    // Поиск аналогов опрашивает сервер при открытии редактора: без мока тест
    // ждал бы реального отказа сети и падал под нагрузкой.
    getAnalogsState: vi.fn().mockResolvedValue({
      run_id: null, status: null, processed: 0, total: 0,
      results: [], error: null, created_at: null,
    }),
    getDocumentHistory: vi.fn().mockResolvedValue([]),
  };
});

import * as api from '../api/documents';
import DocumentEditor from '../components/editor/DocumentEditor';
import { useDocumentEditorStore } from '../stores/documentEditor';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';

/**
 * Рабочий потолок — 2000 позиций (решение пользователя, вопрос 15).
 * Проверяем не «красиво ли», а два риска: что таблица не рисует все строки
 * разом и что подготовка данных не превращается в секунды ожидания.
 */
const ROW_COUNT = 2000;

function storedRows(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    row_id: `r${i}`,
    cells: {
      'Тип': i % 2 === 0 ? 'Работа' : 'Материал',
      'Наименование': `Позиция номер ${i}`,
      'Ед. изм': 'м2',
      'Кол-во': i + 1,
      'Цена работ': 100 + i,
      'Стоимость работ': (i + 1) * (100 + i),
    },
  }));
}

beforeEach(() => {
  vi.clearAllMocks();
  useDocumentEditorStore.getState().reset();

  vi.mocked(api.getDocumentMeta).mockResolvedValue({
    card_id: 'card-1', kind: 'list', row_format: 'generic', file_slot: 'result',
    task_id: 'task-1', task_type: 'LIST_FROM_GRAND', task_status: 'completed',
    can_write: true, readonly_reason: null, rev: 0, active_version_id: 'v1',
    versions: [], coefficient: null, has_draft: false, draft_updated_at: null,
    lock: null, project: { overhead_pct: 3, transport_pct: 3 },
  });
  vi.mocked(api.getDocumentRows).mockResolvedValue({
    version_id: 'v1', rev: 0, rows: storedRows(ROW_COUNT), draft_rows: null,
  });
});

describe('документ на 2000 позиций', () => {
  it('таблица рисует окно строк, а не все две тысячи', async () => {
    const { container } = render(<DocumentEditor cardId="card-1" kind="list" />);

    await waitFor(() => {
      expect(screen.getByText(`Строк: ${ROW_COUNT}`)).toBeInTheDocument();
    });

    const rendered = container.querySelectorAll('[role="row"]');
    expect(rendered.length).toBeGreaterThan(0);
    expect(rendered.length).toBeLessThan(200);
  });

  it('подготовка строк и колонок укладывается в бюджет', () => {
    const stored = storedRows(ROW_COUNT);

    const started = performance.now();
    const grid = genericAdapter.toGrid(stored);
    const columns = genericAdapter.columns(grid);
    const back = genericAdapter.fromGrid(grid);
    const elapsed = performance.now() - started;

    expect(grid).toHaveLength(ROW_COUNT);
    expect(back).toHaveLength(ROW_COUNT);
    expect(columns.length).toBeGreaterThan(0);
    // Открытие документа не должно ощущаться паузой: 300 мс — потолок с запасом
    // на медленную машину, реально на порядок быстрее.
    expect(elapsed).toBeLessThan(300);
  });

  it('поиск и итоги по двум тысячам строк считаются быстро', () => {
    const grid = genericAdapter.toGrid(storedRows(ROW_COUNT));

    const started = performance.now();
    const found = grid.filter((row) =>
      genericAdapter.searchText(row).toLowerCase().includes('номер 199'));
    const totals = genericAdapter.totals(grid, { overhead_pct: 3, transport_pct: 3 });
    const elapsed = performance.now() - started;

    expect(found.length).toBeGreaterThan(0);
    expect(totals).not.toBeNull();
    expect(elapsed).toBeLessThan(150);
  });

  it('итоги считаются по типу строки, а проценты берутся из настроек проекта', () => {
    const grid = genericAdapter.toGrid(storedRows(4));
    const totals = genericAdapter.totals(grid, { overhead_pct: 10, transport_pct: 0 })!;

    // Работы — строки 0 и 2: 1×100 + 3×102 = 406
    expect(totals.sumWork).toBe(406);
    expect(totals.overhead).toBeCloseTo(40.6);
    expect(totals.transport).toBe(0);
  });
});
