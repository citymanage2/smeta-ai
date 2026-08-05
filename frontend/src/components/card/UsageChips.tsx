import React from 'react'
import {
  UsageTotals,
  formatDuration,
  formatTokens,
  formatUsd,
} from '../../utils/usageMetrics'

/**
 * Затраты на ИИ одной строкой: токены · $ · ожидание · работа · допы.
 *
 * План: `plans/2026-08-06-metriki-zatrat-po-stadiyam.md`, Фаза 5.
 *
 * Один компонент на три места — заголовок стадии, строку сметы и шапку
 * проекта: цифры везде одни и те же, расходиться им нельзя. Сами суммы
 * считает `utils/usageMetrics`, здесь только показ.
 *
 * Цифры обновляются с каждым опросом карточек (5 секунд). Отдельного
 * посекундного таймера нет: показатель минутного масштаба, а таймер на каждую
 * строку списка смет — заметная плата ни за что.
 */

interface Props {
  usage: UsageTotals
  /** `stage` — компактно, в заголовке секции; `total` — с подписью «Сумма затрат». */
  variant?: 'stage' | 'total'
  /** Итог по проекту: ожидание и работа складываются во «время реализации». */
  mergeTime?: boolean
}

const TOKENS_HINT =
  'Токены: input + output + чтение и запись кэша, за все прогоны стадии'
const COST_HINT = 'Стоимость запросов к ИИ в долларах, за все прогоны стадии'
const QUEUE_HINT = 'Сколько задача ждала очереди (последний прогон)'
const WORK_HINT = 'Сколько задача считалась (последний прогон)'
const EXTRA_HINT =
  'Допзапросы: поиск цены, аналоги, шаги оптимизации — всё, что запрашивалось ' +
  'у ИИ после того, как файл стадии уже был сформирован'
const TIME_HINT = 'Время реализации: ожидание в очереди плюс работа'

function Chip({
  label,
  value,
  hint,
  accent = false,
}: {
  /** Пустой — показывается только значение (доллары говорят сами за себя). */
  label?: string
  value: string
  hint: string
  accent?: boolean
}) {
  return (
    <span
      title={hint}
      style={{
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: '4px',
        fontSize: '11px',
        lineHeight: 1.4,
        color: accent ? '#7c3aed' : '#64748b',
        whiteSpace: 'nowrap',
      }}
    >
      {label && <span style={{ color: '#94a3b8' }}>{label}</span>}
      <span style={{ fontWeight: 600, color: accent ? '#7c3aed' : '#334155' }}>{value}</span>
    </span>
  )
}

function Separator() {
  return <span style={{ color: '#e2e8f0', fontSize: '11px' }}>·</span>
}

export const UsageChips: React.FC<Props> = ({ usage, variant = 'stage', mergeTime = false }) => {
  // Нет ни одной стадии с метриками — молчим: пустая строка чипов только шумит.
  if (!usage.hasData) return null

  const chips: React.ReactNode[] = [
    <Chip key="tokens" label="токены" value={formatTokens(usage.tokens)} hint={TOKENS_HINT} />,
    <Chip key="usd" value={formatUsd(usage.costUsd)} hint={COST_HINT} />,
  ]

  if (mergeTime) {
    chips.push(
      <Chip
        key="time"
        label="время"
        value={formatDuration(usage.queueSeconds + usage.workSeconds)}
        hint={TIME_HINT}
      />,
    )
  } else {
    chips.push(
      <Chip
        key="queue"
        label="ожидание"
        value={formatDuration(usage.queueSeconds)}
        hint={QUEUE_HINT}
      />,
      <Chip
        key="work"
        label={usage.running ? 'работа, идёт' : 'работа'}
        value={formatDuration(usage.workSeconds)}
        hint={WORK_HINT}
      />,
    )
  }

  // Допы показываем только когда они были: ноль допов — обычное состояние
  // стадии, и постоянный «допы —» в строке ничего не сообщает.
  if (usage.extraTokens > 0 || usage.extraCostUsd > 0) {
    chips.push(
      <Chip
        key="extra"
        label="допы"
        value={`${formatTokens(usage.extraTokens)} / ${formatUsd(usage.extraCostUsd)}`}
        hint={EXTRA_HINT}
        accent
      />,
    )
  }

  return (
    <span
      data-testid="usage-chips"
      style={{
        display: 'inline-flex',
        alignItems: 'baseline',
        flexWrap: 'wrap',
        gap: '6px',
      }}
    >
      {variant === 'total' && (
        <span style={{ fontSize: '11px', fontWeight: 600, color: '#64748b' }}>
          Сумма затрат:
        </span>
      )}
      {chips.map((chip, index) => (
        <React.Fragment key={index}>
          {index > 0 && <Separator />}
          {chip}
        </React.Fragment>
      ))}
    </span>
  )
}

export default UsageChips
