import { EstimationStatus, TaskStatus } from '../types'

// ---------------------------------------------------------------------------
// Единый статус задачи/сметы (Фаза 6, КП-6).
//
// В UI показываем ОДНО согласованное представление: состояние текущей стадии
// (идёт / готово / ошибка / ожидает) как основной сигнал, а бизнес-факт
// estimation_status — как тонкую пометку («рассчитана» / «оптимизирована» /
// «идёт оптимизация»), НЕ как второй равноправный цветной бейдж.
//
// Палитра состояний — та же, что в SmetaList/PipelineStepper/brand-guidelines
// (не плодим пятый вариант цветов). SmetaList импортирует STATE_STYLE отсюда.
// ---------------------------------------------------------------------------

/** Состояние текущей стадии по техническому статусу задачи. */
export const STATE_STYLE: Record<TaskStatus, { label: string; color: string }> = {
  completed: { label: 'Готово', color: '#10b981' },
  processing: { label: 'Идёт', color: '#3b82f6' },
  pending: { label: 'В очереди', color: '#f59e0b' },
  paused: { label: 'На паузе', color: '#b45309' },
  failed: { label: 'Ошибка', color: '#ef4444' },
  cancelled: { label: 'Отменено', color: '#94a3b8' },
}

/** Нет задачи на стадии — стадия ещё не запускалась. */
export const WAITING_STATE = { label: 'Ожидает', color: '#94a3b8' }

/**
 * Бизнес-факт из estimation_status — тонкая пометка, а не бейдж.
 * `optimizing` не теряется: выражаем как «идёт оптимизация» (состояние стадии
 * оптимизации, которое на строке задачи отдельным узлом не показано).
 */
const ESTIMATION_NOTE: Record<EstimationStatus, string | null> = {
  optimized: 'оптимизирована',
  estimated: 'рассчитана',
  optimizing: 'идёт оптимизация',
  unestimated: null,
  not_applicable: null,
}

export interface TaskStatusView {
  /** Подпись состояния стадии: Готово / Идёт / Ошибка / Ожидает … */
  stateLabel: string
  /** Цвет-токен состояния (совпадает со степпером/списком смет). */
  color: string
  /** Тонкая бизнес-пометка или null, если добавлять нечего. */
  note: string | null
}

/**
 * Единый статус: на вход технический статус (+ опционально estimation_status),
 * на выход — состояние стадии + бизнес-пометка. Один язык для всех мест.
 */
export function taskStatusView(status: string, estimation?: EstimationStatus): TaskStatusView {
  const state = STATE_STYLE[status as TaskStatus] ?? WAITING_STATE
  return {
    stateLabel: state.label,
    color: state.color,
    note: estimation ? ESTIMATION_NOTE[estimation] ?? null : null,
  }
}
