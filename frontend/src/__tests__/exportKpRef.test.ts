/**
 * Фаза 8в: пометка «цена из КП» доезжает до строк выгрузки служебным ключом
 * `__kp_ref` — по нему сервер заливает строку в xlsx.
 */
import { describe, expect, it } from 'vitest';

import {
  ExportRow, collapseExportRows, rowsFromEditor,
} from '../components/editor/exportBuilder';
import { estimateAdapter } from '../components/editor/adapters/estimateAdapter';
import { CollapseFields, GridRow } from '../components/editor/adapters/types';

const KP_REF = {
  request_id: 'r1', supplier: 'ООО Кабель', includes_materials: true,
  field: 'price_work', price: 150,
};
const COLUMNS = [{ key: 'name', label: 'Наименование', numeric: false }];

describe('kp_ref в выгрузке', () => {
  it('строка с kp_ref получает __kp_ref, без него — нет, колонкой он не становится', () => {
    const rows = [
      { __key: 'a', name: 'Монтаж', price_work: 150, kp_ref: KP_REF },
      { __key: 'b', name: 'Кабель', kp_ref: null },
    ] as unknown as GridRow[];
    const exported = rowsFromEditor(rows, COLUMNS, () => 'work');
    expect(exported[0].__kp_ref).toEqual(KP_REF);
    expect('__kp_ref' in exported[1]).toBe(false);
    expect('kp_ref' in exported[0]).toBe(false);
  });

  it('редактор сметы хранит kp_ref в строке таблицы и отдаёт его при сохранении', () => {
    const grid = estimateAdapter.toGrid([{ id: 'x', type: 'work', name: 'Монтаж', kp_ref: KP_REF }]);
    expect(grid[0].kp_ref).toEqual(KP_REF);
    const saved = estimateAdapter.fromGrid(grid) as Array<Record<string, unknown>>;
    expect(saved[0].kp_ref).toEqual(KP_REF);
  });

  it('свёртка: одиночная строка пометку сохраняет, группа — нет', () => {
    const fields = estimateAdapter.collapseFields!([]) as CollapseFields;
    const rows: ExportRow[] = [
      { _id: 'a', _kind: 'work', name: 'Монтаж', unit: 'м', qty: 1, __kp_ref: KP_REF },
      { _id: 'b', _kind: 'work', name: 'Лоток', unit: 'м', qty: 1, __kp_ref: KP_REF },
      { _id: 'c', _kind: 'work', name: 'лоток', unit: 'м', qty: 2 },
    ];
    const out = collapseExportRows(rows, fields);
    const single = out.find((row) => row.name === 'Монтаж')!;
    const group = out.find((row) => String(row.name).toLowerCase() === 'лоток')!;
    expect(single.__kp_ref).toEqual(KP_REF);
    expect(group.__kp_ref).toBeUndefined();
  });
});
