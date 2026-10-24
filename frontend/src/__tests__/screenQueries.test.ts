/**
 * Помощник «число из текста» сам по себе: на нём держатся проверки сумм в
 * тестах экранов, и ошибка разбора сделала бы их все неверными разом.
 */
import { describe, expect, it } from 'vitest';

import { numberAfter, numbersIn, parseScreenNumber } from './screenQueries';

describe('число из текста экрана', () => {
  it.each([
    ['9 800,00 ₽', 9800],
    ['9 800,00 ₽', 9800],
    [(1234567.5).toLocaleString('ru-RU') + ' ₽', 1234567.5],
    ['$450,00', 450],
    ['+50 000 ₽', 50000],
    ['−1 200', -1200],
    ['+20%', 20],
    ['0,61', 0.61],
  ])('«%s» → %d', (text, expected) => {
    expect(parseScreenNumber(text)).toBe(expected);
  });

  it('не угадывает, если чисел нет или несколько', () => {
    expect(() => parseScreenNumber('Цена не определена')).toThrow();
    expect(() => parseScreenNumber('Накладные расходы 20%: 800,00 ₽')).toThrow();
    expect(numbersIn('Накладные расходы 20%: 800,00 ₽')).toEqual([20, 800]);
    expect(numberAfter('Накладные расходы 20%: 800,00 ₽', 'Накладные расходы 20%:')).toBe(800);
  });
});
