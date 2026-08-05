import { describe, expect, it } from 'vitest';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';

/**
 * Номер позиции исходной сметы стоит в перечне первой колонкой — и в файле,
 * и в редакторе. План: plans/2026-08-06-nomer-pozicii-iz-ishodnoj-smety.md
 */

const listRow = {
  row_id: 'r1',
  cells: {
    '№ в исходной смете': 1,
    '№ п/п': 1,
    'Тип': 'Работа',
    'Наименование': 'Пробивка гнезд',
    'Ед. изм': '100 шт',
    'Кол-во': 0.02,
    'Примечание': '',
  },
};

describe('перечень: номер позиции исходной сметы', () => {
  it('колонка идёт первой, перед типом и наименованием', () => {
    const grid = genericAdapter.toGrid([listRow]);
    const keys = genericAdapter.columns(grid).map((c) => c.key);
    expect(keys.slice(0, 3)).toEqual(['№ в исходной смете', 'Тип', 'Наименование']);
  });

  it('колонка редактируемая и не числовая — «1.1» и «2а» остаются как есть', () => {
    const grid = genericAdapter.toGrid([
      { row_id: 'r1', cells: { ...listRow.cells, '№ в исходной смете': '1.1' } },
    ]);
    const column = genericAdapter.columns(grid).find((c) => c.key === '№ в исходной смете');
    expect(column).toBeDefined();
    expect(column!.numeric).toBe(false);
    expect(column!.editable).toBe(true);
    expect(genericAdapter.displayValue(grid[0], '№ в исходной смете')).toBeNull();
  });

  it('без колонки порядок прежний — тип, наименование, остальное', () => {
    const grid = genericAdapter.toGrid([
      {
        row_id: 'r1',
        cells: { '№ п/п': 1, 'Тип': 'Работа', 'Наименование': 'Пробивка', 'Кол-во': 1 },
      },
    ]);
    const keys = genericAdapter.columns(grid).map((c) => c.key);
    expect(keys).toEqual(['Тип', 'Наименование', '№ п/п', 'Кол-во']);
  });

  it('правка строки номер не теряет', () => {
    const grid = genericAdapter.toGrid([listRow]);
    const edited = { ...grid[0], 'Кол-во': 0.05 };
    const [stored] = genericAdapter.fromGrid([edited]) as Array<{
      cells: Record<string, unknown>;
    }>;
    expect(stored.cells['№ в исходной смете']).toBe(1);
    expect(stored.cells['Кол-во']).toBe(0.05);
  });
});
