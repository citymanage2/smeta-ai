import React from 'react'
import { ProgressSummary } from '../../types/workflow'

interface ProgressCounterProps {
  data?: ProgressSummary | null
}

/**
 * Конкретный прогресс идущего этапа «N из M» из безопасной выжимки progress_data.
 *
 * - Есть счётчик частей (total > 1) → полоса + «N из M частей» (+ «найдено X позиций»).
 * - Есть только число позиций → неопределённый «Найдено X позиций…».
 * - Нет числовых данных → null (вызывающий показывает спиннер + progress_message).
 */
export function ProgressCounter({ data }: ProgressCounterProps): React.ReactElement | null {
  if (!data) return null

  const total = data.total_chunks ?? data.chunks_total
  const done = data.chunks_done
  const items = data.items_count

  const hasChunkBar =
    typeof total === 'number' &&
    total > 1 &&
    typeof done === 'number' &&
    done >= 0

  if (hasChunkBar) {
    const clampedDone = Math.min(done as number, total as number)
    const pct = Math.max(0, Math.min(100, Math.round((clampedDone / (total as number)) * 100)))
    return (
      <div style={{ margin: '4px 0 2px', minWidth: 0 }}>
        <div
          role="progressbar"
          aria-valuenow={clampedDone}
          aria-valuemin={0}
          aria-valuemax={total}
          aria-label={`${clampedDone} из ${total} частей`}
          style={{ background: '#e2e8f0', borderRadius: 4, height: 6, overflow: 'hidden' }}
        >
          <div
            data-testid="progress-counter-fill"
            style={{
              width: `${pct}%`,
              height: '100%',
              background: '#3b82f6',
              transition: 'width 0.3s ease',
            }}
          />
        </div>
        <div style={{ fontSize: '11px', color: '#64748b', marginTop: 3 }}>
          {clampedDone} из {total} частей
          {typeof items === 'number' && items > 0 ? ` · найдено ${items} позиций` : ''}
        </div>
      </div>
    )
  }

  if (typeof items === 'number' && items > 0) {
    return (
      <div style={{ fontSize: '11px', color: '#64748b', margin: '4px 0 2px' }}>
        Найдено {items} позиций…
      </div>
    )
  }

  return null
}
