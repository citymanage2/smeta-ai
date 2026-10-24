/**
 * Умения таблицы, которых не хватало единому редактору.
 *
 * Фаза 12 плана `plans/2026-08-02-edinyy-redaktor-tablic.md`, сверка с критериями
 * приёмки спеки. Три умения были у старой таблицы сметы, но при переезде на
 * единое ядро не переехали:
 *
 * - перетаскивание строк мышкой;
 * - удаление работы вместе с её материалами;
 * - подсветка строк: вычет, исключённая позиция, цена из прайса, группы А/В/С.
 */
import { describe, expect, it } from 'vitest';

import { moveRow, removeRowsCascade } from '../components/editor/rowOps';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';
import { GridRow } from '../components/editor/adapters/types';

const ROWS: GridRow[] = [
  { __key: 'w1', type: 'Работа', name: 'Кладка стен', qty: 10, price_work: 1000 },
  { __key: 'm1', type: 'Материал', name: 'Кирпич', qty: 500, work_row_id: 'w1' },
  { __key: 'm2', type: 'Материал', name: 'Раствор', qty: 20, work_row_id: 'w1' },
  { __key: 'w2', type: 'Работа', name: 'Штукатурка', qty: 30, price_work: 500 },
  { __key: 'm3', type: 'Материал', name: 'Смесь', qty: 60, work_row_id: 'w2' },
];

const names = (rows: GridRow[]) => rows.map((row) => row.__key);

// ---------------------------------------------------------------------------
// Перетаскивание строк
// ---------------------------------------------------------------------------

describe('перетаскивание строк', () => {
  it('переносит строку выше цели', () => {
    const result = moveRow(ROWS, 'w2', 'w1', true);

    expect(names(result)).toEqual(['w2', 'w1', 'm1', 'm2', 'm3']);
  });

  it('переносит строку ниже цели', () => {
    const result = moveRow(ROWS, 'w1', 'w2', false);

    expect(names(result)).toEqual(['m1', 'm2', 'w2', 'w1', 'm3']);
  });

  it('перенос на саму себя ничего не меняет', () => {
    expect(moveRow(ROWS, 'w1', 'w1', true)).toEqual(ROWS);
  });

  it('неизвестная строка ничего не ломает', () => {
    expect(moveRow(ROWS, 'нет-такой', 'w1', true)).toEqual(ROWS);
  });

  it('строки не теряются и не дублируются', () => {
    const result = moveRow(ROWS, 'm3', 'm1', true);

    expect(result).toHaveLength(ROWS.length);
    expect(new Set(names(result)).size).toBe(ROWS.length);
  });
});

// ---------------------------------------------------------------------------
// Удаление работы вместе с её материалами
// ---------------------------------------------------------------------------

describe('удаление строк', () => {
  it('удаление работы уносит её материалы', () => {
    const result = removeRowsCascade(ROWS, new Set(['w1']), estimateAdapter);

    expect(names(result)).toEqual(['w2', 'm3']);
  });

  it('удаление материала работу не трогает', () => {
    const result = removeRowsCascade(ROWS, new Set(['m1']), estimateAdapter);

    expect(names(result)).toEqual(['w1', 'm2', 'w2', 'm3']);
  });

  it('удаление двух работ уносит материалы обеих', () => {
    const result = removeRowsCascade(ROWS, new Set(['w1', 'w2']), estimateAdapter);

    expect(result).toHaveLength(0);
  });

  it('в плоском документе связей нет — удаляется ровно отмеченное', () => {
    const flat: GridRow[] = [
      { __key: 'r1', 'Наименование': 'A' },
      { __key: 'r2', 'Наименование': 'Б' },
    ];

    const result = removeRowsCascade(flat, new Set(['r1']), genericAdapter);

    expect(names(result)).toEqual(['r2']);
  });
});
