/**
 * Цели оптимизации: одна формула отклонения на весь фронтенд.
 *
 * План: `plans/2026-09-01-celi-optimizacii.md`.
 *
 * Отклонение показывается в трёх местах — бланк сводной, карточка проекта,
 * список проектов, — и везде должно означать одно и то же. Поэтому и расчёт, и
 * формат живут здесь, а не переписываются в каждом экране.
 * Зеркало на сервере — `_target` и `_deviation` в `utils/summary_calc.py`.
 */

/**
 * Цель: число либо null — «цели нет».
 *
 * Пустая ячейка и ноль — разные вещи: ноль человек мог поставить осознанно, и
 * отклонение по нему считается. Отрицательной цели не бывает — такую считаем
 * незаданной, чтобы промах не показывался зелёным из-за знака.
 */
export function targetValue(value: number | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const number = Number(value);
  if (!Number.isFinite(number) || number < 0) return null;
  return number;
}

export interface Deviation {
  value: number | null;
  /** Процент считается только при цели больше нуля: делить на ноль нельзя. */
  pct: number | null;
}

export function targetDeviation(fact: number, target: number | null): Deviation {
  if (target === null) return { value: null, pct: null };
  const value = fact - target;
  return { value, pct: target > 0 ? (value / target) * 100 : null };
}

/** Отклонение со знаком: «+» у превышения цели, минус подставит форматирование. */
export const fmtSignedMoney = (n: number) =>
  (n > 0 ? '+' : '') + Math.round(n).toLocaleString('ru-RU') + ' ₽';

export const fmtDeviationPct = (n: number) =>
  (n > 0 ? '+' : '') + n.toLocaleString('ru-RU', { maximumFractionDigits: 1 }) + '%';

/** Превышение цели — красное, попадание в цель и экономия — зелёное. */
export const deviationColor = (n: number) => (n > 0 ? '#dc2626' : '#059669');
