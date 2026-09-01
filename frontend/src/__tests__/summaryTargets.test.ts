/**
 * Цели оптимизации: отклонения на экране.
 *
 * План: `plans/2026-09-01-celi-optimizacii.md`, Фаза 3.
 *
 * Числа здесь те же, что в серверном тесте
 * (`backend/tests/test_summary_targets.py`), и набор данных тот же, что в
 * регрессе сводной. Правило проекта №4: экран и файл считают по одной формуле —
 * значит, и сверять их надо одними числами.
 */
import { describe, expect, it } from 'vitest';

import { calcSummary } from '../stores/summaryEditorStore';
import { SectionTab, SummaryOverrides } from '../types/summary';
import { OVERRIDES as BASE_OVERRIDES, SECTIONS as BASE_SECTIONS } from './summaryRegressFixture';

const SECTIONS: SectionTab[] = [
  { ...BASE_SECTIONS[0], target_works: 15000, target_materials: 20000 },
  { ...BASE_SECTIONS[1], target_materials: 40000 },
];

const OVERRIDES: SummaryOverrides = {
  ...BASE_OVERRIDES,
  target_total_for_customer: 200000,
};

const byName = (calc: ReturnType<typeof calcSummary>) =>
  Object.fromEntries(calc.section_totals.map((s) => [s.card_name, s]));

describe('цели оптимизации', () => {
  it('отклонение считается от себестоимости, если база «из сметы»', () => {
    const ar = byName(calcSummary(SECTIONS, { ...OVERRIDES, target_basis: 'cost' })).АР;

    expect(ar.target_works).toBe(15000);
    expect(ar.works_fact).toBeCloseTo(17932.53125, 8);
    expect(ar.works_deviation).toBeCloseTo(2932.53125, 8);
    expect(ar.works_deviation_pct).toBeCloseTo(19.550208333333334, 8);
    expect(ar.materials_fact).toBeCloseTo(18921.024, 8);
    expect(ar.materials_deviation).toBeCloseTo(-1078.976, 8);
    expect(ar.materials_deviation_pct).toBeCloseTo(-5.39488, 8);
  });

  it('база по умолчанию — себестоимость', () => {
    const calc = calcSummary(SECTIONS, OVERRIDES);
    expect(calc.target_basis).toBe('cost');
    expect(byName(calc).АР.works_fact).toBeCloseTo(17932.53125, 8);
  });

  it('база «с НДС» сравнивает с суммой после налога раздела', () => {
    const ar = byName(calcSummary(SECTIONS, { ...OVERRIDES, target_basis: 'with_vat' })).АР;
    expect(ar.works_fact).toBeCloseTo(20981.0615625, 8);
    expect(ar.works_deviation).toBeCloseTo(5981.0615625, 8);
    expect(ar.materials_fact).toBeCloseTo(22137.59808, 8);
    expect(ar.materials_deviation).toBeCloseTo(2137.59808, 8);
  });

  it('без цели отклонения нет — это не ноль', () => {
    const ov = byName(calcSummary(SECTIONS, OVERRIDES)).ОВ;
    expect(ov.target_works).toBeNull();
    expect(ov.works_deviation).toBeNull();
    expect(ov.works_deviation_pct).toBeNull();
    expect(ov.materials_deviation).toBeCloseTo(125, 8);
  });

  it('ИТОГО считает только разделы с целью', () => {
    const calc = calcSummary(SECTIONS, OVERRIDES);
    expect(calc.targets_total_works).toBe(15000);
    expect(calc.targets_fact_works).toBeCloseTo(17932.53125, 8);
    expect(calc.targets_deviation_works).toBeCloseTo(2932.53125, 8);
    expect(calc.targets_total_materials).toBe(60000);
    expect(calc.targets_fact_materials).toBeCloseTo(59046.024, 8);
    expect(calc.targets_deviation_materials).toBeCloseTo(-953.976, 8);
    expect(calc.targets_deviation_materials_pct).toBeCloseTo(-1.58996, 8);
  });

  it('цель по объекту сравнивается с итогом для заказчика', () => {
    const calc = calcSummary(SECTIONS, OVERRIDES);
    expect(calc.total_for_customer).toBeCloseTo(222647.81997720266, 6);
    expect(calc.total_deviation).toBeCloseTo(22647.819977202656, 6);
    expect(calc.total_deviation_pct).toBeCloseTo(11.32390998860133, 8);
  });

  it('цель 0 даёт отклонение, но не процент', () => {
    const calc = calcSummary(
      [{ ...BASE_SECTIONS[1], target_works: 0 }],
      { ...BASE_OVERRIDES, coefficient: 1, target_total_for_customer: 0 },
    );
    expect(calc.section_totals[0].works_deviation).toBeCloseTo(3999.96, 8);
    expect(calc.section_totals[0].works_deviation_pct).toBeNull();
    expect(calc.total_deviation_pct).toBeNull();
  });

  it('отрицательная цель считается незаданной', () => {
    const calc = calcSummary(
      [{ ...BASE_SECTIONS[1], target_works: -100 }],
      { ...BASE_OVERRIDES, target_total_for_customer: -5 },
    );
    expect(calc.section_totals[0].target_works).toBeNull();
    expect(calc.section_totals[0].works_deviation).toBeNull();
    expect(calc.target_total_for_customer).toBeNull();
    expect(calc.total_deviation).toBeNull();
  });

  it('сводная без целей считается как раньше', () => {
    const calc = calcSummary(BASE_SECTIONS, BASE_OVERRIDES);
    expect(calc.has_section_targets).toBe(false);
    expect(calc.total_deviation).toBeNull();
    expect(calc.targets_total_works).toBeNull();
    expect(calc.total_for_customer).toBeCloseTo(222647.81997720266, 6);
  });
});
