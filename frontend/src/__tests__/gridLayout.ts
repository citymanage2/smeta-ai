/**
 * Таблица редактора в jsdom (план `plans/2026-10-25-chistka-testov.md`, фаза 5).
 *
 * Зачем. В jsdom нет ни размеров, ни ResizeObserver: react-data-grid считает
 * таблицу нулевой и не рисует ни одной ячейки. Тест, которому нужна ячейка —
 * прочитать число, дважды щёлкнуть, поставить курсор перед вставкой, — без
 * этого видит пустую таблицу. Раньше приём копировался в каждый файл.
 *
 * Как пользоваться — один вызов на уровне файла, до тестов:
 *
 *   withGridLayout();
 *
 * Подмена ставится перед тестами файла и снимается после них.
 */
import { afterAll, beforeAll } from 'vitest';

export function withGridLayout(): void {
  let width: PropertyDescriptor | undefined;
  let rect: typeof HTMLElement.prototype.getBoundingClientRect;
  let scroll: typeof Element.prototype.scrollIntoView;
  let observer: unknown;

  beforeAll(() => {
    width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
      configurable: true, value: 2000,
    });
    rect = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function fake() {
      return {
        width: 2000, height: 600, top: 0, left: 0, right: 2000,
        bottom: 600, x: 0, y: 0, toJSON: () => ({}),
      } as DOMRect;
    };
    observer = (globalThis as { ResizeObserver?: unknown }).ResizeObserver;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
    scroll = Element.prototype.scrollIntoView;
    Element.prototype.scrollIntoView = () => {};
  });

  afterAll(() => {
    if (width) Object.defineProperty(HTMLElement.prototype, 'clientWidth', width);
    else delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
    HTMLElement.prototype.getBoundingClientRect = rect;
    (globalThis as { ResizeObserver?: unknown }).ResizeObserver = observer;
    Element.prototype.scrollIntoView = scroll;
  });
}
