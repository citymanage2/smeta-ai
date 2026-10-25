/**
 * Форматирование прогноза времени.
 *
 * План: plans/2026-07-30-eta-ocheredi-zadach.md, Фаза 5.
 */
import { describe, it, expect } from 'vitest'
import { describeEta, formatDuration, formatQueuePosition, TaskEta } from '../utils/eta'

function makeEta(overrides: Partial<TaskEta> = {}): TaskEta {
  return {
    starts_in_s: 0,
    ready_in_s: 2400,
    ready_at: new Date(Date.now() + 2400_000).toISOString(),
    rough: false,
    finishing: false,
    units: 1200,
    unit_kind: 'items',
    ...overrides,
  }
}

describe('formatDuration', () => {
  it('минуты, часы и «меньше минуты»', () => {
    expect(formatDuration(20)).toBe('меньше минуты')
    expect(formatDuration(2400)).toBe('40 мин')
    expect(formatDuration(3600)).toBe('1 ч')
    expect(formatDuration(4200)).toBe('1 ч 10 мин')
  })
})

describe('describeEta', () => {
  it('считающаяся задача — время по часам и относительно', () => {
    const view = describeEta(makeEta(), 'processing')!
    // Часы не проверяются: после 23:20 оценка попадает на другой день и к ним
    // добавляется дата.
    expect(view.ready).toContain('через 40 мин')
    expect(view.start).toBe('')
  })

  it('ожидающая задача — ещё и когда стартует', () => {
    const view = describeEta(makeEta({ starts_in_s: 1500, ready_in_s: 4200 }), 'pending')!
    expect(view.start).toBe('старт ≈ через 25 мин')
    expect(view.ready).toContain('через 1 ч 10 мин')
  })

  it('очередь свободна — стартует сразу', () => {
    const view = describeEta(makeEta({ starts_in_s: 0 }), 'pending')!
    expect(view.start).toBe('старт вот-вот')
  })

  it('расчётное время вышло — «завершается», без отрицательных чисел', () => {
    const view = describeEta(makeEta({ finishing: true, ready_in_s: 60 }), 'processing')!
    expect(view.ready).toBe('завершается')
  })

  it.each([true, false])('грубая оценка помечается: rough=%s', (rough) => {
    expect(describeEta(makeEta({ rough }), 'processing')!.rough).toBe(rough)
  })

  it('подсказка разделяет ожидание и расчёт', () => {
    const hint = describeEta(makeEta({ starts_in_s: 1500, ready_in_s: 4200 }), 'pending')!.hint
    expect(hint).toContain('Ожидание очереди: 25 мин')
    expect(hint).toContain('Расчёт: 45 мин')
  })

  it('завершённая задача и отсутствие прогноза — показывать нечего', () => {
    expect(describeEta(makeEta(), 'completed')).toBeNull()
    expect(describeEta(null, 'processing')).toBeNull()
    expect(describeEta(undefined, 'pending')).toBeNull()
  })
})

/**
 * Место в очереди. Задачи считаются строго по одной (решение 30.07.2026:
 * параллельная обработка на этой машине не выживала), поэтому очередь читается
 * как очередь, а «меня возьмут третьей» — факт, в отличие от оценки в минутах.
 *
 * План: plans/2026-07-30-parallelnaya-obrabotka-umiraet.md, Фаза 8.
 */
describe('место в очереди', () => {
  // Первая названа «следующая», а не «1-я»; нет позиции — нет строки.
  it.each([
    [1, 'следующая в очереди'],
    [3, '3-я в очереди'],
    [11, '11-я в очереди'],
    [null, ''],
    [undefined, ''],
    [0, ''],
  ])('позиция %s → «%s»', (position, expected) => {
    expect(formatQueuePosition(position)).toBe(expected)
  })

  it('ожидающая задача показывает позицию', () => {
    const view = describeEta(makeEta({ starts_in_s: 1200, queue_position: 3 }), 'pending')!
    expect(view.position).toBe('3-я в очереди')
    expect(view.hint).toContain('Место в очереди: 3')
  })

  it('считающаяся задача позицию не показывает — она уже не в очереди', () => {
    const view = describeEta(makeEta({ queue_position: 2 }), 'processing')!
    expect(view.position).toBe('')
  })
})
