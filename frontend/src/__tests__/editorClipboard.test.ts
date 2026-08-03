import { describe, expect, it } from 'vitest';
import {
  applyPaste, describePaste, extractRange, parseTsv, toTsv,
} from '../components/editor/clipboard';
import { EditorColumn, GridRow } from '../components/editor/adapters/types';
import { genericAdapter } from '../components/editor/adapters/genericAdapter';

const columns: EditorColumn[] = [
  { key: 'Наименование', name: 'Наименование', width: 200, editable: true, numeric: false },
  { key: 'Кол-во', name: 'Кол-во', width: 90, editable: true, numeric: true },
  { key: 'Цена работ', name: 'Цена работ', width: 100, editable: true, numeric: true },
  { key: 'Стоимость работ', name: 'Стоимость работ', width: 110, editable: false, numeric: true, computed: true },
];

function rows(): GridRow[] {
  return [
    { __key: 'r1', 'Наименование': 'Работа A', 'Кол-во': 1, 'Цена работ': 100, 'Стоимость работ': 100 },
    { __key: 'r2', 'Наименование': 'Работа Б', 'Кол-во': 2, 'Цена работ': 200, 'Стоимость работ': 400 },
    { __key: 'r3', 'Наименование': 'Работа В', 'Кол-во': 3, 'Цена работ': 300, 'Стоимость работ': 900 },
  ];
}

describe('разбор буфера обмена', () => {
  it('читает то, что Excel кладёт в буфер: табуляции и переводы строк', () => {
    expect(parseTsv('a\tb\nc\td')).toEqual([['a', 'b'], ['c', 'd']]);
  });

  it('не создаёт лишнюю строку из хвостового перевода строки', () => {
    expect(parseTsv('a\tb\n')).toEqual([['a', 'b']]);
  });

  it('понимает перевод строки в стиле Windows', () => {
    expect(parseTsv('a\tb\r\nc\td')).toEqual([['a', 'b'], ['c', 'd']]);
  });

  it('пустой буфер даёт пустой результат, а не строку с пустой ячейкой', () => {
    expect(parseTsv('')).toEqual([]);
  });

  it('собирает обратно в формат, который понимает Excel', () => {
    expect(toTsv([[1, 'два'], [null, 4]])).toBe('1\tдва\n\t4');
  });
});

describe('копирование диапазона', () => {
  it('отдаёт прямоугольный кусок в порядке строк и колонок', () => {
    const matrix = extractRange(rows(), columns, { top: 0, left: 1, bottom: 1, right: 2 });
    expect(matrix).toEqual([[1, 100], [2, 200]]);
  });

  it('не выходит за границы таблицы', () => {
    const matrix = extractRange(rows(), columns, { top: 2, left: 2, bottom: 99, right: 99 });
    expect(matrix).toEqual([[300, 900]]);
  });

  it('нормализует диапазон, выделенный снизу вверх', () => {
    const matrix = extractRange(rows(), columns, { top: 2, left: 2, bottom: 1, right: 1 });
    expect(matrix).toEqual([[2, 200], [3, 300]]);
  });
});

describe('вставка в таблицу', () => {
  it('накладывает кусок начиная с выбранной ячейки', () => {
    const outcome = applyPaste({
      rows: rows(), columns, anchorRow: 0, anchorColumn: 1,
      matrix: [['10', '1000'], ['20', '2000']],
    });
    expect(outcome.applied).toBe(4);
    expect(outcome.rows[0]['Кол-во']).toBe(10);
    expect(outcome.rows[1]['Цена работ']).toBe(2000);
    expect(outcome.rows[2]['Кол-во']).toBe(3); // третью строку не трогали
  });

  it('вставка больше таблицы обрезается, а не создаёт строки', () => {
    const outcome = applyPaste({
      rows: rows(), columns, anchorRow: 2, anchorColumn: 1,
      matrix: [['10'], ['20'], ['30']],
    });
    expect(outcome.rows).toHaveLength(3);
    expect(outcome.droppedRows).toBe(2);
    expect(outcome.rows[2]['Кол-во']).toBe(10);
  });

  it('вставка шире таблицы обрезается по колонкам', () => {
    const outcome = applyPaste({
      rows: rows(), columns, anchorRow: 0, anchorColumn: 2,
      matrix: [['500', 'лишнее', 'ещё лишнее']],
    });
    expect(outcome.droppedColumns).toBe(1);
    expect(outcome.rows[0]['Цена работ']).toBe(500);
  });

  it('вставка меньше выделения меняет только то, что вставили', () => {
    const before = rows();
    const outcome = applyPaste({
      rows: before, columns, anchorRow: 1, anchorColumn: 1, matrix: [['7']],
    });
    expect(outcome.applied).toBe(1);
    expect(outcome.rows[1]['Кол-во']).toBe(7);
    expect(outcome.rows[0]).toBe(before[0]); // нетронутые строки — те же объекты
    expect(outcome.rows[2]).toBe(before[2]);
  });

  it('нечисло в числовой колонке не затирает старое значение', () => {
    const outcome = applyPaste({
      rows: rows(), columns, anchorRow: 0, anchorColumn: 1, matrix: [['не число']],
    });
    expect(outcome.rejectedCells).toBe(1);
    expect(outcome.applied).toBe(0);
    expect(outcome.rows[0]['Кол-во']).toBe(1);
  });

  it('число с запятой и пробелами разбирается как число', () => {
    const outcome = applyPaste({
      rows: rows(), columns, anchorRow: 0, anchorColumn: 2, matrix: [['1 234,5']],
    });
    expect(outcome.rows[0]['Цена работ']).toBe(1234.5);
  });

  it('вычисляемая колонка пропускается — стоимость считается, а не вставляется', () => {
    const outcome = applyPaste({
      rows: rows(), columns, anchorRow: 0, anchorColumn: 3, matrix: [['999999']],
    });
    expect(outcome.skippedReadonly).toBe(1);
    expect(outcome.rows[0]['Стоимость работ']).toBe(100);
  });

  it('после вставки цены стоимость пересчитывается сама', () => {
    const outcome = applyPaste({
      rows: rows(), columns, anchorRow: 1, anchorColumn: 2,
      matrix: [['250']],
      recalc: genericAdapter.recalc,
    });
    expect(outcome.rows[1]['Цена работ']).toBe(250);
    expect(outcome.rows[1]['Стоимость работ']).toBe(500); // 2 × 250
  });

  it('пустой буфер ничего не меняет', () => {
    const before = rows();
    const outcome = applyPaste({
      rows: before, columns, anchorRow: 0, anchorColumn: 0, matrix: [],
    });
    expect(outcome.rows).toBe(before);
    expect(outcome.applied).toBe(0);
  });

  it('сообщает пользователю, что именно произошло', () => {
    const outcome = applyPaste({
      rows: rows(), columns, anchorRow: 2, anchorColumn: 1,
      matrix: [['10'], ['нет'], ['30']],
    });
    const text = describePaste(outcome);
    expect(text).toContain('Вставлено значений: 1');
    expect(text).toContain('отброшено 2');
  });

  it('без изменений сообщение не показывается', () => {
    expect(describePaste({
      rows: [], applied: 0, droppedRows: 0, droppedColumns: 0,
      rejectedCells: 0, skippedReadonly: 0,
    })).toBeNull();
  });
});
