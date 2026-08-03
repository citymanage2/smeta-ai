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
    // Если оценка попадает на другой день, часы показываются с датой
    // («≈ 03.08 00:10»). Тест гонялся в любое время суток и после 23:20 падал
    // на ровном месте — дата в шаблоне необязательна.
    expect(view.ready).toMatch(/^≈ (\d{2}\.\d{2} )?\d{2}:\d{2} \(через 40 мин\)$/)
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

  it('грубая оценка помечается и объясняется', () => {
    const view = describeEta(makeEta({ rough: true }), 'processing')!
    expect(view.rough).toBe(true)
    expect(view.hint).toContain('мало данных')
  })

  it('подсказка показывает объём работы со склонением', () => {
    expect(describeEta(makeEta({ units: 1200 }), 'processing')!.hint).toContain('1200 позиций')
    expect(describeEta(makeEta({ units: 2 }), 'processing')!.hint).toContain('2 позиции')
    expect(describeEta(makeEta({ units: 1 }), 'processing')!.hint).toContain('1 позиция')
    expect(
      describeEta(makeEta({ units: 48, unit_kind: 'pages' }), 'processing')!.hint
    ).toContain('48 страниц')
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
  it('первая в очереди названа «следующая», а не «1-я»', () => {
    expect(formatQueuePosition(1)).toBe('следующая в очереди')
  })

  it('остальные — по номеру', () => {
    expect(formatQueuePosition(3)).toBe('3-я в очереди')
    expect(formatQueuePosition(11)).toBe('11-я в очереди')
  })

  it('нет позиции — нет строки', () => {
    expect(formatQueuePosition(null)).toBe('')
    expect(formatQueuePosition(undefined)).toBe('')
    expect(formatQueuePosition(0)).toBe('')
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

  it('без позиции с бэкенда строка пустая, остальное работает', () => {
    const view = describeEta(makeEta({ starts_in_s: 600 }), 'pending')!
    expect(view.position).toBe('')
    expect(view.start).toBe('старт ≈ через 10 мин')
  })
})
