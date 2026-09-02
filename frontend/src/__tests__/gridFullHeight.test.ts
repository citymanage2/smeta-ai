import { describe, expect, it } from 'vitest';
import { MIN_GRID_HEIGHT, fitGridHeight } from '../components/editor/gridHeight';

/**
 * Высота «на весь экран» считается по факту: раньше это была константа
 * `100vh - 320px`, и таблица либо уезжала под край окна, либо оставляла
 * пустую полосу — смотря сколько обвязки стоит над ней в этот раз.
 */
describe('высота таблицы на весь экран', () => {
  it('таблица кончается ровно там, где кончается видимая область', () => {
    // Область прокрутки 100…800; таблица начинается на 300; под таблицей
    // 56 px (подвал редактора и отступы страницы).
    const height = fitGridHeight({
      gridTop: 300, gridBottom: 860, viewTop: 100, viewBottom: 800, contentBottom: 916,
    });
    expect(height).toBe(444); // 800 − 300 − 56
    // Проверка на устойчивость: пересчёт с новой высотой даёт то же число.
    expect(fitGridHeight({
      gridTop: 300, gridBottom: 300 + height, viewTop: 100, viewBottom: 800,
      contentBottom: 300 + height + 56,
    })).toBe(height);
  });

  it('обвязка выросла — таблица стала ниже ровно на столько же', () => {
    const before = fitGridHeight({
      gridTop: 300, gridBottom: 700, viewTop: 0, viewBottom: 800, contentBottom: 740,
    });
    const after = fitGridHeight({
      gridTop: 340, gridBottom: 740, viewTop: 0, viewBottom: 800, contentBottom: 780,
    });
    expect(before - after).toBe(40);
  });

  it('под таблицей ничего нет — считаем до низа области', () => {
    expect(fitGridHeight({
      gridTop: 200, gridBottom: 600, viewTop: 0, viewBottom: 900, contentBottom: 600,
    })).toBe(700);
  });

  it('таблицу увели выше края окна — считаем от края, а не от её верха', () => {
    expect(fitGridHeight({
      gridTop: -150, gridBottom: 500, viewTop: 0, viewBottom: 800, contentBottom: 500,
    })).toBe(800);
  });

  it('места почти нет — таблица не схлопывается в рамку', () => {
    expect(fitGridHeight({
      gridTop: 700, gridBottom: 760, viewTop: 0, viewBottom: 800, contentBottom: 1200,
    })).toBe(MIN_GRID_HEIGHT);
  });
});

describe('замер по DOM', () => {
  /** Прямоугольник, какой вернул бы браузер. */
  const rect = (top: number, height: number) => () => ({
    top, bottom: top + height, height, left: 0, right: 0, width: 0, x: 0, y: top,
    toJSON: () => ({}),
  } as DOMRect);

  it('считает от области прокрутки, а не от окна', async () => {
    const { measureGridHeight } = await import('../components/editor/gridHeight');

    // Разметка Layout: <main> прокручивается, под ним подвал, в окно не влезающий.
    const main = document.createElement('div');
    main.style.overflowY = 'auto';
    const page = document.createElement('div');
    const grid = document.createElement('div');
    page.appendChild(grid);
    main.appendChild(page);
    document.body.appendChild(main);

    // Область прокрутки видна с 96 по 760; содержимого в ней 900 px, прокручено на 0.
    main.getBoundingClientRect = rect(96, 664);
    Object.defineProperty(main, 'scrollHeight', { value: 900, configurable: true });
    Object.defineProperty(main, 'scrollTop', { value: 0, configurable: true });
    // Таблица начинается на 300 и сейчас высотой 560; под ней 40 px отступов.
    grid.getBoundingClientRect = rect(300, 560);

    // contentBottom = 96 + 900 = 996, ниже таблицы 996 − 860 = 136.
    expect(measureGridHeight(grid)).toBe(760 - 300 - 136);
    document.body.removeChild(main);
  });
});
