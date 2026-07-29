/**
 * Отображение прогноза времени по задаче.
 *
 * Бэкенд (app/services/eta_service.py) присылает оценку в секундах, округлённую
 * до минуты. Здесь она превращается в текст: и относительно («через 40 мин»),
 * и по часам («≈ 14:10») — первое отвечает на «долго ли ждать», второе на
 * «успею ли до встречи». Везде «≈»: это оценка, а не обещание.
 */

export interface TaskEta {
  /** Секунд до старта обработки. 0 — задача уже считается. */
  starts_in_s: number
  /** Секунд до результата, включая ожидание в очереди. */
  ready_in_s: number
  /** То же абсолютным временем (ISO, UTC). */
  ready_at: string
  /** Прогноз грубый: нет замера объёма или ещё нет истории по типу задачи. */
  rough: boolean
  /** Расчётное время вышло, а задача всё ещё идёт. */
  finishing: boolean
  units: number | null
  unit_kind: string | null
}

const UNIT_LABELS: Record<string, [string, string, string]> = {
  items: ['позиция', 'позиции', 'позиций'],
  rows: ['строка', 'строки', 'строк'],
  pages: ['страница', 'страницы', 'страниц'],
}

/** Русское склонение по числу: 1 позиция, 2 позиции, 5 позиций. */
function plural(n: number, forms: [string, string, string]): string {
  const mod100 = n % 100
  if (mod100 >= 11 && mod100 <= 14) return forms[2]
  const mod10 = n % 10
  if (mod10 === 1) return forms[0]
  if (mod10 >= 2 && mod10 <= 4) return forms[1]
  return forms[2]
}

/** «меньше минуты» / «40 мин» / «1 ч 10 мин». */
export function formatDuration(seconds: number): string {
  const minutes = Math.round(seconds / 60)
  if (minutes < 1) return 'меньше минуты'
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`
}

/** Время по часам пользователя: «14:10». Для завтрашних сроков — «14:10, зв». */
export function formatClock(iso: string): string {
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return ''
  const time = date.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  const now = new Date()
  const sameDay =
    date.getDate() === now.getDate() &&
    date.getMonth() === now.getMonth() &&
    date.getFullYear() === now.getFullYear()
  if (sameDay) return time
  // Через сутки и дальше час без даты вводил бы в заблуждение.
  return `${date.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })} ${time}`
}

export interface EtaView {
  /** Главная строка: «≈ 14:10 (через 40 мин)» или «завершается». */
  ready: string
  /** Для ожидающих задач: «старт ≈ через 25 мин». Пусто, если стартует сразу. */
  start: string
  /** Подсказка при наведении: из чего сложился прогноз. */
  hint: string
  /** Прогноз грубый — интерфейс показывает это явно. */
  rough: boolean
}

/**
 * Текст прогноза для задачи. null — показывать нечего (задача не активна или
 * прогноза нет).
 */
export function describeEta(eta: TaskEta | null | undefined, status: string): EtaView | null {
  if (!eta) return null
  if (status !== 'pending' && status !== 'processing') return null

  const ready = eta.finishing
    ? 'завершается'
    : `≈ ${formatClock(eta.ready_at)} (через ${formatDuration(eta.ready_in_s)})`

  let start = ''
  if (status === 'pending') {
    start = eta.starts_in_s > 0
      ? `старт ≈ через ${formatDuration(eta.starts_in_s)}`
      : 'старт вот-вот'
  }

  const parts: string[] = []
  if (eta.units && eta.unit_kind && UNIT_LABELS[eta.unit_kind]) {
    parts.push(`Объём: ${eta.units} ${plural(eta.units, UNIT_LABELS[eta.unit_kind])}`)
  }
  if (status === 'pending' && eta.starts_in_s > 0) {
    parts.push(`Ожидание очереди: ${formatDuration(eta.starts_in_s)}`)
    parts.push(`Расчёт: ${formatDuration(eta.ready_in_s - eta.starts_in_s)}`)
  }
  parts.push(
    eta.rough
      ? 'Оценка грубая: пока мало данных о похожих задачах'
      : 'Оценка по времени похожих задач'
  )

  return { ready, start, hint: parts.join(' · '), rough: eta.rough }
}
