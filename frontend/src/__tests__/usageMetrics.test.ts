/**
 * Суммы затрат по смете и по проекту — точные числа.
 *
 * План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 5.
 *
 * Три места показывают одни и те же деньги: заголовок стадии, строка сметы,
 * шапка проекта. Расчёт один — здесь он и проверяется, чтобы расхождение
 * ловилось тестом, а не глазами на планёрке.
 */
import { describe, expect, it } from 'vitest'
import { TaskBrief, TaskUsage, WorkflowCard } from '../types/workflow'
import {
  cardEstimateCost,
  cardUsage,
  formatDuration,
  formatTokens,
  formatUsd,
  projectUsage,
  stageUsage,
} from '../utils/usageMetrics'

function usage(over: Partial<TaskUsage> = {}): TaskUsage {
  return {
    tokens: 0,
    cost_usd: 0,
    extra_tokens: 0,
    extra_cost_usd: 0,
    queue_seconds: null,
    work_seconds: null,
    queue_running: false,
    work_running: false,
    ...over,
  }
}

function task(over: Partial<TaskBrief> = {}): TaskBrief {
  return {
    id: 't1',
    task_type: 'ESTIMATE_FROM_LIST',
    status: 'completed',
    name: null,
    created_at: '2026-08-06T10:00:00Z',
    input_files: [],
    progress_message: null,
    ...over,
  }
}

function card(over: Partial<WorkflowCard> = {}): WorkflowCard {
  return {
    id: 'c1',
    project_id: 'p1',
    name: 'АР',
    stage: 'estimate',
    list_task_id: null,
    completeness_task_id: null,
    estimate_task_id: null,
    optimization_task_id: null,
    list_task: null,
    completeness_task: null,
    estimate_task: null,
    optimization_task: null,
    primary_version_id: null,
    created_at: '2026-08-06T10:00:00Z',
    updated_at: '2026-08-06T10:00:00Z',
    ...over,
  }
}

describe('stageUsage', () => {
  it('складывает допы в общие токены и деньги, но оставляет их отдельно', () => {
    const u = stageUsage(usage({
      tokens: 1000, cost_usd: 1.25, extra_tokens: 200, extra_cost_usd: 0.5,
    }))
    expect(u.tokens).toBe(1200)
    expect(u.costUsd).toBe(1.75)
    expect(u.extraTokens).toBe(200)
    expect(u.extraCostUsd).toBe(0.5)
    expect(u.hasData).toBe(true)
  })

  it('стадия без метрик не даёт данных — чипы не рисуются', () => {
    expect(stageUsage(null).hasData).toBe(false)
    expect(stageUsage(undefined).hasData).toBe(false)
  })

  it('растущий счётчик помечен как идущий', () => {
    expect(stageUsage(usage({ work_running: true })).running).toBe(true)
    expect(stageUsage(usage({ queue_running: true })).running).toBe(true)
    expect(stageUsage(usage()).running).toBe(false)
  })
})

describe('cardUsage', () => {
  it('AC-5: итог по смете равен сумме её стадий, включая допы', () => {
    const c = card({
      list_task: task({ id: 'l', usage: usage({ tokens: 100, cost_usd: 0.1, queue_seconds: 30, work_seconds: 60 }) }),
      completeness_task: task({ id: 'c', usage: usage({ tokens: 200, cost_usd: 0.2, queue_seconds: 10, work_seconds: 40 }) }),
      estimate_task: task({
        id: 'e',
        usage: usage({
          tokens: 5000, cost_usd: 8.5, extra_tokens: 300, extra_cost_usd: 0.75,
          queue_seconds: 120, work_seconds: 900,
        }),
      }),
      optimization_task: task({ id: 'o', usage: usage({ tokens: 400, cost_usd: 0.4, queue_seconds: 5, work_seconds: 100 }) }),
    })

    const u = cardUsage(c)
    expect(u.tokens).toBe(100 + 200 + 5000 + 300 + 400)
    expect(u.costUsd).toBeCloseTo(0.1 + 0.2 + 8.5 + 0.75 + 0.4, 6)
    expect(u.extraTokens).toBe(300)
    expect(u.extraCostUsd).toBe(0.75)
    expect(u.queueSeconds).toBe(30 + 10 + 120 + 5)
    expect(u.workSeconds).toBe(60 + 40 + 900 + 100)
  })

  it('смета без единой стадии с метриками ничего не показывает', () => {
    expect(cardUsage(card()).hasData).toBe(false)
  })

  it('незаполненные стадии не превращаются в нули времени', () => {
    const c = card({ estimate_task: task({ usage: usage({ tokens: 10, cost_usd: 0.01 }) }) })
    const u = cardUsage(c)
    expect(u.queueSeconds).toBe(0)
    expect(u.workSeconds).toBe(0)
    expect(u.hasData).toBe(true)
  })
})

describe('projectUsage', () => {
  it('AC-6: итог по проекту равен сумме итогов его смет', () => {
    const first = card({
      estimate_task: task({ usage: usage({ tokens: 1000, cost_usd: 2, queue_seconds: 60, work_seconds: 300 }) }),
    })
    const second = card({
      id: 'c2',
      estimate_task: task({ usage: usage({ tokens: 2500, cost_usd: 5.5, extra_tokens: 100, extra_cost_usd: 0.25, queue_seconds: 30, work_seconds: 600 }) }),
    })

    const u = projectUsage([first, second])
    expect(u.tokens).toBe(1000 + 2500 + 100)
    expect(u.costUsd).toBeCloseTo(2 + 5.5 + 0.25, 6)
    expect(u.queueSeconds).toBe(90)
    expect(u.workSeconds).toBe(900)
    expect(u.hasData).toBe(true)
  })

  it('проект без смет молчит', () => {
    expect(projectUsage([]).hasData).toBe(false)
  })
})

describe('cardEstimateCost', () => {
  it('AC-7: оптимизация важнее сметы', () => {
    const c = card({
      estimate_task: task({ id: 'e', cost: 1000 }),
      optimization_task: task({ id: 'o', cost: 850 }),
    })
    expect(cardEstimateCost(c)).toBe(850)
  })

  it('без оптимизации берётся сумма сметы', () => {
    expect(cardEstimateCost(card({ estimate_task: task({ cost: 1000 }) }))).toBe(1000)
  })

  it('сметы нет — null, а не ноль', () => {
    expect(cardEstimateCost(card())).toBeNull()
    expect(cardEstimateCost(card({ estimate_task: task({ cost: null }) }))).toBeNull()
  })
})

describe('форматирование', () => {
  it('токены — порядок величины', () => {
    expect(formatTokens(0)).toBe('—')
    expect(formatTokens(940)).toBe('940')
    expect(formatTokens(1234)).toBe('1.2K')
    expect(formatTokens(1_234_567)).toBe('1.2M')
  })

  it('доллары — с центами, мелочь не теряется в нуле', () => {
    expect(formatUsd(0)).toBe('—')
    expect(formatUsd(0.004)).toBe('<$0.01')
    expect(formatUsd(9.837)).toBe('$9.84')
  })

  it('длительность — по-русски', () => {
    expect(formatDuration(null)).toBe('—')
    expect(formatDuration(0)).toBe('—')
    expect(formatDuration(45)).toBe('45 сек')
    expect(formatDuration(12 * 60)).toBe('12 мин')
    expect(formatDuration(72 * 60)).toBe('1 ч 12 мин')
  })
})
