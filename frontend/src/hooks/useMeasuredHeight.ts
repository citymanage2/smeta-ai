import { useCallback, useLayoutEffect, useState } from 'react'

/**
 * Высота элемента в пикселях — для «этажей» закреплённых шапок.
 *
 * Шапки на странице проекта прилипают друг под другом: переключатель вида,
 * строка «Сметы (N) + Добавить смету», заголовок таблицы. Каждая следующая
 * должна знать суммарную высоту предыдущих, иначе они наедут друг на друга.
 * Числа не зашиваем: размеры зависят от шрифта и переносов кнопок.
 *
 * Ref — колбэком, а не useRef: измеряемый блок появляется позже самого хука
 * (сначала страница показывает лоадер), и эффект с пустыми зависимостями
 * увидел бы null и остался бы с нулевой высотой навсегда.
 *
 * ResizeObserver есть не везде (в jsdom его нет) — тогда меряем на появлении
 * узла и по ресайзу окна. Высота 0 безопасна: шапка просто прилипнет к верху.
 */
export function useMeasuredHeight<T extends HTMLElement>() {
  const [node, setNode] = useState<T | null>(null)
  const [height, setHeight] = useState(0)
  const ref = useCallback((el: T | null) => setNode(el), [])

  useLayoutEffect(() => {
    if (!node) return

    const measure = () => setHeight(node.getBoundingClientRect().height)
    measure()

    const RO = (window as unknown as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver
    if (RO) {
      const observer = new RO(measure)
      observer.observe(node)
      return () => observer.disconnect()
    }

    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [node])

  return { ref, height }
}
