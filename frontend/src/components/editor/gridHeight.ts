/**
 * Высота таблицы в режиме «на весь экран».
 *
 * Раньше высота была константой `calc(100vh - 320px)`. Константа обязана врать:
 * над таблицей стоит переменная обвязка (вкладки версий, тулбар в одну или две
 * строки, вкладки листов, полоса итогов, баннер присутствия), под ней — подвал
 * Layout и отступы страницы, а сам редактор открывается и страницей, и внутри
 * карточки, где над ним ещё полстраницы. Промах в обе стороны видно сразу:
 * лишние пиксели загоняют таблицу под край окна и заставляют скроллить
 * страницу, недостача оставляет пустую полосу.
 *
 * Поэтому высота считается по факту: от верха таблицы до низа видимой области
 * прокрутки, минус всё, что стоит под таблицей внутри этой области.
 */

export interface GridFit {
  /** Верх таблицы в координатах окна. */
  gridTop: number;
  /** Низ таблицы в координатах окна. */
  gridBottom: number;
  /** Верх видимой части области прокрутки. */
  viewTop: number;
  /** Низ видимой части области прокрутки. */
  viewBottom: number;
  /** Низ всего содержимого области прокрутки (с учётом прокрутки и отступов). */
  contentBottom: number;
}

/** Ниже таблица не сжимается: пустая рамка бесполезнее короткого списка. */
export const MIN_GRID_HEIGHT = 240;

export function fitGridHeight(fit: GridFit): number {
  // Всё, что стоит под таблицей: подвал редактора, отступ страницы, нижний
  // отступ области прокрутки, соседние блоки. Меряем, а не перечисляем.
  const below = Math.max(0, fit.contentBottom - fit.gridBottom);
  // Таблица уехала выше края окна (страницу прокрутили) — считаем от края,
  // иначе высота вырастет на невидимую часть.
  const top = Math.max(fit.gridTop, fit.viewTop);
  return Math.max(MIN_GRID_HEIGHT, Math.round(fit.viewBottom - top - below));
}

/** Ближайший прокручиваемый предок; его нет — прокручивается само окно. */
export function scrollParent(el: HTMLElement): HTMLElement | null {
  let node = el.parentElement;
  while (node) {
    const overflow = getComputedStyle(node).overflowY;
    // Проверять «а прокручивается ли он сейчас» нельзя: пока таблица короткая,
    // область не переполнена, и мы бы приняли за неё окно — вместе с подвалом,
    // который в окно не входит.
    if (overflow === 'auto' || overflow === 'scroll') return node;
    node = node.parentElement;
  }
  return null;
}

/** Замер по живому DOM. Возвращает null, если мерить нечего (jsdom, скрытый узел). */
export function measureGridHeight(grid: HTMLElement): number | null {
  const rect = grid.getBoundingClientRect();
  if (!rect.height && !rect.top) return null;
  const scroller = scrollParent(grid);
  const fit: GridFit = scroller
    ? {
      gridTop: rect.top,
      gridBottom: rect.bottom,
      viewTop: scroller.getBoundingClientRect().top,
      viewBottom: scroller.getBoundingClientRect().bottom,
      contentBottom: scroller.getBoundingClientRect().top - scroller.scrollTop + scroller.scrollHeight,
    }
    : {
      gridTop: rect.top,
      gridBottom: rect.bottom,
      viewTop: 0,
      viewBottom: window.innerHeight,
      contentBottom: document.documentElement.scrollHeight - document.documentElement.scrollTop,
    };
  return fitGridHeight(fit);
}
