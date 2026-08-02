import { EstimateRow } from '../types';
import { SectionTab, SummaryOverrides } from '../types/summary';

/**
 * Опорный набор данных для регресса сводной (план 2026-08-02, Фаза 7).
 *
 * Итоги сводной считает `calcSummary`. Фаза 7 переводит разделы на единый
 * редактор, и главное требование пользователя — цифры бланка «Сводная» не
 * должны измениться ни на копейку. Этот набор специально «неудобный»: вычет
 * (отрицательный объём), строка-раздел без цен, свои налоги у разделов,
 * коэффициент, скрытые строки бланка и добавленная вручную строка затрат.
 */

function row(over: Partial<EstimateRow> & { id: string }): EstimateRow {
  return {
    lineage_id: over.id,
    num: 1,
    type: 'work',
    name: 'Строка',
    unit: 'м2',
    qty: 1,
    price_work: null,
    price_material: null,
    cost: null,
    selected: false,
    ...over,
  } as EstimateRow;
}

export const SECTIONS: SectionTab[] = [
  {
    card_id: 'card-1',
    card_name: 'АР',
    version_id: 'v-1',
    version_display_name: 'Исходная смета',
    tax_pct: 5,
    rows: [
      row({ id: 'r1', type: 'section', name: 'Раздел 1', qty: null }),
      row({ id: 'r2', type: 'work', qty: 12.5, price_work: 1340.75 }),
      row({ id: 'r3', type: 'material', qty: 8, price_material: 2210.4 }),
      // Вычет: объём < 0 стоимости не даёт.
      row({ id: 'r4', type: 'work', qty: -3, price_work: 1000 }),
    ],
  },
  {
    card_id: 'card-2',
    card_name: 'ОВ',
    version_id: 'v-2',
    version_display_name: 'V3 — Технологии',
    tax_pct: 0,
    rows: [
      row({ id: 'r5', type: 'work', qty: 4, price_work: 999.99 }),
      row({ id: 'r6', type: 'material', qty: 2.5, price_material: 15000 }),
    ],
  },
];

export const OVERRIDES: SummaryOverrides = {
  coefficient: 1.07,
  transport_pct: 3,
  cleanup_pct: 2.5,
  overhead_pct: 4,
  daily_workers_cost: 2,
  bank_guarantee_cost: 12000,
  cleaning_cost: 5000,
  ppr_cost: 7000,
  commissioning_cost: 0,
  construction_control_cost: 3000,
  author_supervision_cost: 0,
  passes_cost: 1500,
  site_office_cost: 0,
  travel_cost: 0,
  rp_cost: 0,
  housing_rent_cost: 0,
  workers_transport_cost: 800,
  contingency_pct: 2,
  profit_pct: 20,
  vat_full_cost_pct: 22,
  tax_pct: 2,
  hidden_fixed_rows: ['cleanup', 'ppr'],
  custom_rows_before: [
    { id: 'c1', label: 'Аренда лесов', qty_pct: '1 шт', without_vat: 25000 },
  ],
  custom_rows_after: [],
};
