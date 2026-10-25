import { describe, expect, it } from 'vitest';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';

/**
 * Номер позиции исходной сметы стоит в перечне первой колонкой — и в файле,
 * и в редакторе. План: plans/2026-08-06-nomer-pozicii-iz-ishodnoj-smety.md
 */

/** Заголовок колонки — один на все стадии (`source_numbers.SOURCE_NO_HEADER`). */
const SOURCE_NO_HEADER = '№ в исходной смете';

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
  it('колонка идёт первой, где бы ни стояла в строке', () => {
    // В ячейках номер стоит после типа и наименования — в таблице он всё равно первый.
    const { '№ в исходной смете': sourceNo, ...rest } = listRow.cells;
    const grid = genericAdapter.toGrid([
      { row_id: 'r1', cells: { ...rest, [SOURCE_NO_HEADER]: sourceNo } },
    ]);
    expect(genericAdapter.columns(grid)[0].name).toBe(SOURCE_NO_HEADER);
  });

  it('колонка редактируемая и не числовая — «1.1» и «2а» остаются как есть', () => {
    const grid = genericAdapter.toGrid([
      { row_id: 'r1', cells: { ...listRow.cells, '№ в исходной смете': '1.1' } },
    ]);
    const column = genericAdapter.columns(grid).find((c) => c.key === '№ в исходной смете');
    expect(column).toBeDefined();
    expect(column!.numeric).toBe(false);
    expect(column!.editable).toBe(true);
    expect(genericAdapter.displayValue?.(grid[0], '№ в исходной смете')).toBeNull();
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
