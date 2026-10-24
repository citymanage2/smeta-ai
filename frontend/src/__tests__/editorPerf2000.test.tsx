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

/**
 * Рабочий потолок — 2000 позиций (решение пользователя, вопрос 15).
 * Проверяем не «красиво ли», а риск: таблица не рисует все строки разом.
 *
 * Замеры времени в миллисекундах здесь были и убраны: в jsdom под нагрузкой
 * они мигали, а не ловили поломку. Итоги перечня проверяются с точными числами
 * в `coefficient.test.tsx` («единый расчёт итогов»).
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
      expect(screen.getByTestId('document-editor-grid'))
      .toHaveAttribute('data-row-count', String(ROW_COUNT));
    });

    const rendered = container.querySelectorAll('[role="row"]');
    expect(rendered.length).toBeGreaterThan(0);
    expect(rendered.length).toBeLessThan(200);
  });
});
