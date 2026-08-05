import { describe, expect, it } from 'vitest';
import fs from 'fs';
import path from 'path';

import { genericAdapter } from '../components/editor/adapters/genericAdapter';
import { GridRow } from '../components/editor/adapters/types';

/**
 * Строки, дописанные комплектом материалов, должны быть видны глазом: человек
 * решает, оставить ли их в смете, и обязан отличать их от позиций заказчика.
 * Признак — префикс примечания: строки документа приходят из xlsx, служебные
 * поля в них не переживают сохранение.
 */

const row = (note: string, name = 'Профиль стоечный ПС 50х50'): GridRow => ({
  __key: 'r1',
  'Тип': 'Материал',
  'Наименование': name,
  'Ед. изм': 'м',
  'Кол-во': 10.95,
  'Примечание': note,
});

describe('подсветка комплекта материалов', () => {
  it('добавленная по норме строка помечена', () => {
    const css = genericAdapter.rowClass?.(
      row('Добавлено по норме: 5,475 × 2 = 10,95 м. КНАУФ С-111.'),
    );
    expect(css).toContain('de-row-kit-added');
  });

  it('расхождение объёма помечено отдельно', () => {
    const css = genericAdapter.rowClass?.(
      row('Расхождение с нормой: по норме 21,9 м2, в файле 5,475 м2 — проверьте.'),
    );
    expect(css).toContain('de-row-kit-mismatch');
    expect(css).not.toContain('de-row-kit-added');
  });

  it('позиция заказчика не подсвечивается', () => {
    expect(genericAdapter.rowClass?.(row(''))).toBeUndefined();
    expect(genericAdapter.rowClass?.(row('Соответствует норме'))).toBeUndefined();
  });

  it('колонка примечания опознаётся по началу названия', () => {
    const withDot: GridRow = {
      __key: 'r2',
      'Наименование': 'Дюбель-гвоздь 6х40',
      'Примечание.': 'Добавлено по норме: 5,475 × 1,6 = 9 шт.',
    };
    expect(genericAdapter.rowClass?.(withDot)).toContain('de-row-kit-added');
  });

  it('документ без колонки примечания работает как раньше', () => {
    const plain: GridRow = { __key: 'r3', 'Наименование': 'Позиция', 'Кол-во': 1 };
    expect(genericAdapter.rowClass?.(plain)).toBeUndefined();
  });

  it('оба класса описаны в стилях редактора', () => {
    const css = fs.readFileSync(
      path.resolve(__dirname, '../components/editor/DocumentEditor.css'),
      'utf-8',
    );
    expect(css).toContain('de-row-kit-added');
    expect(css).toContain('de-row-kit-mismatch');
  });
});

describe('подсветка комплекта в смете', () => {
  it('строка комплекта видна и после перехода в смету', async () => {
    const { estimateAdapter } = await import('../components/editor/adapters/estimateAdapter');
    const css = estimateAdapter.rowClass?.({
      __key: 'm1', type: 'Материал', name: 'Лист гипсоволокнистый ГВЛ 12,5 мм',
      qty: 21.9, price_material: 420,
      notes: 'Добавлено по норме: 5,475 × 4 (2 слоя × 2 стороны) = 21,9 м2.',
    });
    expect(css).toContain('de-row-kit-added');
  });

  it('расхождение объёма видно и в смете', async () => {
    const { estimateAdapter } = await import('../components/editor/adapters/estimateAdapter');
    const css = estimateAdapter.rowClass?.({
      __key: 'm2', type: 'Материал', name: 'Листы гипсоволокнистые', qty: 5.475,
      notes: 'Расхождение с нормой: по норме 21,9 м2, в файле 5,475 м2 — проверьте.',
    });
    expect(css).toContain('de-row-kit-mismatch');
  });

  it('обычная строка сметы не подсвечивается комплектом', async () => {
    const { estimateAdapter } = await import('../components/editor/adapters/estimateAdapter');
    const css = estimateAdapter.rowClass?.({
      __key: 'm3', type: 'Материал', name: 'Щебень', qty: 39.096,
      notes: 'Соответствует норме',
    });
    expect(css ?? '').not.toContain('de-row-kit');
  });
});
