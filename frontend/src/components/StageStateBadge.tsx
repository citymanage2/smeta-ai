import React from 'react'
import { EstimationStatus } from '../types'
import { taskStatusView } from '../utils/taskStatusView'

// ---------------------------------------------------------------------------
// Единый бейдж состояния стадии (Фаза 6, КП-6).
//
// Одно представление вместо двух конкурирующих: цветная точка + подпись
// состояния (Готово / Идёт / Ошибка / Ожидает) как основной сигнал, а
// estimation_status — тонкой серой пометкой через «·» («рассчитана» и т.п.),
// не отдельным цветным бейджем того же веса.
// ---------------------------------------------------------------------------

interface Props {
  status: string
  estimation?: EstimationStatus
  style?: React.CSSProperties
}

export function StageStateBadge({ status, estimation, style }: Props) {
  const view = taskStatusView(status, estimation)
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        fontSize: 12,
        fontWeight: 600,
        color: view.color,
        ...style,
      }}
    >
      <span
        style={{
          width: 7,
          height: 7,
          borderRadius: '50%',
          background: view.color,
          display: 'inline-block',
          flexShrink: 0,
        }}
      />
      {view.stateLabel}
      {view.note && (
        <span style={{ color: '#94a3b8', fontWeight: 500 }}>· {view.note}</span>
      )}
    </span>
  )
}
