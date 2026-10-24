/**
 * Чтение экрана в тестах: числа из текста и строки таблицы по ролям
 * (план `plans/2026-10-25-chistka-testov.md`, фаза 3).
 *
 * Зачем. Тесты сверяли суммы строкой целиком («9 800,00 ₽») — и падали от смены
 * формата, хотя число верное, — или проверяли `toContain('20')`, что выполняется
 * и при ошибке (20 есть в «2026», в «120»). Строки таблицы искали по классам
 * вёрстки (`.de-grid`, `.rdg-cell`) и по номеру чекбокса. Здесь число читается
 * как число, а строка и ячейка ищутся так, как их видит человек: строка — по
 * наименованию, ячейка — по заголовку колонки.
 *
 * Как пользоваться.
 *
 *   parseScreenNumber('9 800,00 ₽')            // 9800 (ровно одно число в тексте)
 *   numberNextTo('ИТОГО:')                     // число рядом с подписью на экране
 *   const row = getGridRow('Кладка стен');     // строка таблицы по тексту ячейки
 *   parseScreenNumber(cellIn(row, 'Кол-во').textContent)   // 20
 *
 * Разделители разрядов — обычный и неразрывные пробелы (так печатает
 * `toLocaleString('ru-RU')`), дробная часть — после запятой или точки, минус —
 * дефис или «−». Знаки «₽», «$», «%» и слова вокруг игнорируются.
 */
import { screen, within } from '@testing-library/react';

const SPACES = '    ';
const NUMBER = new RegExp(
  `[-−+]?\\d{1,3}(?:[${SPACES}]\\d{3})+(?:[.,]\\d+)?|[-−+]?\\d+(?:[.,]\\d+)?`,
  'g',
);

function toNumber(token: string): number {
  const plain = token
    .replace(new RegExp(`[${SPACES}]`, 'g'), '')
    .replace('−', '-')
    .replace(',', '.');
  return Number(plain);
}

/** Все числа текста по порядку: «Накладные 20%: 800,00 ₽» → [20, 800]. */
export function numbersIn(text: string | null | undefined): number[] {
  return [...(text ?? '').matchAll(NUMBER)].map((match) => toNumber(match[0]));
}

/** Единственное число текста. Чисел нет или больше одного — ошибка, а не догадка. */
export function parseScreenNumber(text: string | null | undefined): number {
  const found = numbersIn(text);
  if (found.length !== 1) {
    throw new Error(`Ожидалось одно число в «${text ?? ''}», найдено: ${found.length}`);
  }
  return found[0];
}

/** Первое число после подписи: numberAfter('ИТОГО: 9 800,00 ₽', 'ИТОГО:') → 9800. */
export function numberAfter(text: string | null | undefined, label: string): number {
  const source = text ?? '';
  const at = source.indexOf(label);
  if (at < 0) throw new Error(`Подписи «${label}» нет в «${source}»`);
  const [first] = numbersIn(source.slice(at + label.length));
  if (first === undefined) throw new Error(`После «${label}» нет числа: «${source}»`);
  return first;
}

/**
 * Число, которое стоит на экране рядом с подписью (в том же блоке, после неё).
 * Подпись ищется как текст элемента — так же, как `getByText`.
 */
export function numberNextTo(label: string | RegExp, container: HTMLElement = document.body): number {
  const labelEl = within(container).getByText(label);
  const labelText = labelEl.textContent ?? '';
  let box: HTMLElement | null = labelEl.parentElement;
  while (box && (box.textContent ?? '').trim() === labelText.trim()) box = box.parentElement;
  return numberAfter(box?.textContent, labelText);
}

function normalized(text: string | null | undefined): string {
  return (text ?? '').replace(/\s+/g, ' ').trim();
}

/** Строка — точное совпадение текста (без лишних пробелов), регэксп — как задан. */
function matches(text: string | null | undefined, expected: string | RegExp): boolean {
  const value = normalized(text);
  return typeof expected === 'string' ? value === expected : expected.test(value);
}

/** Строки данных таблицы (без строки заголовков). */
export function gridRows(grid: HTMLElement = screen.getByRole('grid')): HTMLElement[] {
  return within(grid)
    .getAllByRole('row')
    .filter((row) => within(row).queryAllByRole('columnheader').length === 0);
}

/**
 * Строка таблицы, в одной из ячеек которой есть текст `name` (строка — как
 * подстрока: рядом с наименованием в ячейке бывают значки свёртки и счётчики).
 * Подошло не ровно одной строке — ошибка, а не первая попавшаяся.
 */
export function getGridRow(name: string | RegExp, grid?: HTMLElement): HTMLElement {
  const found = gridRows(grid).filter((row) =>
    within(row).queryAllByRole('gridcell').some((cell) => (
      typeof name === 'string' ? normalized(cell.textContent).includes(name) : name.test(normalized(cell.textContent))
    )),
  );
  if (found.length !== 1) {
    throw new Error(`Строк с «${String(name)}» в таблице: ${found.length}, ожидалась одна`);
  }
  return found[0];
}

/** Ячейка строки под заголовком колонки `column` (по `aria-colindex`, а не по порядку). */
export function cellIn(row: HTMLElement, column: string | RegExp, grid?: HTMLElement): HTMLElement {
  const table = grid ?? (row.closest('[role="grid"], [role="treegrid"]') as HTMLElement | null);
  if (!table) throw new Error('Строка не внутри таблицы');
  const header = within(table)
    .getAllByRole('columnheader')
    .find((cell) => matches(cell.textContent, column));
  if (!header) throw new Error(`Колонки «${String(column)}» в таблице нет`);
  const index = header.getAttribute('aria-colindex');
  const cell = within(row)
    .queryAllByRole('gridcell')
    .find((c) => c.getAttribute('aria-colindex') === index);
  if (!cell) throw new Error(`В строке нет ячейки колонки «${String(column)}»`);
  return cell;
}
