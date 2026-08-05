/**
 * Затраты на ИИ и тайминги — единственная точка расчёта на фронте.
 *
 * План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 5.
 *
 * Итог по смете и итог по проекту складываются здесь, а не в компонентах: три
 * места показывают одни и те же деньги, и разойтись они не должны — тот же
 * принцип, по которому итоги сметы живут в `estimateCalc.ts`.
 *
 * Всё считается из уже поллящегося ответа `workflow-cards`: отдельных запросов
 * за метриками нет.
 */
import { TaskBrief, TaskUsage, WorkflowCard } from '../types/workflow'

/** Свёрнутые показатели: допы уже включены в токены и деньги. */
export interface UsageTotals {
  /** Токены основной обработки + допов. */
  tokens: number
  /** Доллары основной обработки + допов. */
  costUsd: number
  /** Только допы — показываются отдельной парой. */
  extraTokens: number
  extraCostUsd: number
  /** Секунды ожидания в очереди. */
  queueSeconds: number
  /** Секунды фактической работы. */
  workSeconds: number
  /** Хотя бы один счётчик ещё растёт. */
  running: boolean
  /** Есть ли вообще что показывать (была хоть одна стадия с метриками). */
  hasData: boolean
}

const EMPTY: UsageTotals = {
  tokens: 0,
  costUsd: 0,
  extraTokens: 0,
  extraCostUsd: 0,
  queueSeconds: 0,
  workSeconds: 0,
  running: false,
  hasData: false,
}

/** Показатели одной стадии. Стадии без метрик дают hasData: false. */
export function stageUsage(usage: TaskUsage | null | undefined): UsageTotals {
  if (!usage) return EMPTY
  return {
    tokens: usage.tokens + usage.extra_tokens,
    costUsd: usage.cost_usd + usage.extra_cost_usd,
    extraTokens: usage.extra_tokens,
    extraCostUsd: usage.extra_cost_usd,
    queueSeconds: usage.queue_seconds ?? 0,
    workSeconds: usage.work_seconds ?? 0,
    running: usage.queue_running || usage.work_running,
    hasData: true,
  }
}

function add(a: UsageTotals, b: UsageTotals): UsageTotals {
  return {
    tokens: a.tokens + b.tokens,
    costUsd: a.costUsd + b.costUsd,
    extraTokens: a.extraTokens + b.extraTokens,
    extraCostUsd: a.extraCostUsd + b.extraCostUsd,
    queueSeconds: a.queueSeconds + b.queueSeconds,
    workSeconds: a.workSeconds + b.workSeconds,
    running: a.running || b.running,
    hasData: a.hasData || b.hasData,
  }
}

/** Итог по смете — сумма её четырёх стадий, включая допы. */
export function cardUsage(card: WorkflowCard): UsageTotals {
  const stages: (TaskBrief | null)[] = [
    card.list_task, card.completeness_task, card.estimate_task, card.optimization_task,
  ]
  return stages.map((task) => stageUsage(task?.usage)).reduce(add, EMPTY)
}

/** Итог по проекту — сумма его смет. */
export function projectUsage(cards: WorkflowCard[]): UsageTotals {
  return cards.map(cardUsage).reduce(add, EMPTY)
}

/**
 * Сумма сформированной сметы в рублях.
 *
 * Оптимизация важнее сметы: если смету оптимизировали, в тендер идёт её сумма.
 * null — сметы ещё нет, и показывать надо прочерк, а не ноль.
 */
export function cardEstimateCost(card: WorkflowCard): number | null {
  return card.optimization_task?.cost ?? card.estimate_task?.cost ?? null
}

// ---------------------------------------------------------------------------
// Форматирование
// ---------------------------------------------------------------------------

/** 1 234 → «1.2K», 1 234 567 → «1.2M». Порядок величины важнее точной цифры. */
export function formatTokens(tokens: number): string {
  if (tokens <= 0) return '—'
  if (tokens < 1000) return String(tokens)
  if (tokens < 1_000_000) return `${(tokens / 1000).toFixed(1)}K`
  return `${(tokens / 1_000_000).toFixed(1)}M`
}

/** Доллары: центы значимы — смета стоит около $10, и $0.4 допов заметны. */
export function formatUsd(usd: number): string {
  if (usd <= 0) return '—'
  if (usd < 0.01) return '<$0.01'
  return `$${usd.toFixed(2)}`
}

/** Длительность по-русски: «45 сек», «12 мин», «1 ч 12 мин». */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || seconds <= 0) return '—'
  if (seconds < 60) return `${Math.round(seconds)} сек`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  return `${hours} ч ${minutes % 60} мин`
}

/** Рубли сметы — тот же формат, что в шапке проекта. */
export function formatRub(cost: number): string {
  return `${Math.round(cost).toLocaleString('ru-RU')} ₽`
}
