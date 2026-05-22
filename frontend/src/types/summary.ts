import { EstimateRow } from './index';

// Custom row that user manually adds
export interface CustomCostRow {
  id: string
  label: string
  qty_pct: string       // display text for the %/Кол-во column
  without_vat: number   // canonical stored value; with_vat = without_vat × 1.22
}

export interface SummaryOverrides {
  coefficient: number;
  transport_pct: number;
  cleanup_pct: number;
  overhead_pct: number;
  daily_workers_cost: number;        // stores COUNT of workers (×5000 = cost)
  bank_guarantee_cost: number;       // stored as без НДС
  cleaning_cost: number;
  ppr_cost: number;
  commissioning_cost: number;        // row 10: Разнорабочие мусор
  construction_control_cost: number;
  author_supervision_cost: number;
  passes_cost: number;
  site_office_cost: number;
  travel_cost: number;
  rp_cost: number;
  housing_rent_cost: number;
  workers_transport_cost: number;
  contingency_pct: number;
  profit_pct: number;
  vat_full_cost_pct: number;
  tax_pct: number;
  // row management
  hidden_fixed_rows: string[];       // keys of fixed rows removed by user
  custom_rows_before: CustomCostRow[]; // user-added rows above separator (numbered, in subtotal)
  custom_rows_after: CustomCostRow[];  // user-added rows below separator (unnumbered, informational)
  // legacy (kept for backward compat, unused)
  vat_works_pct?: number;
  vat_materials_pct?: number;
}

// All 18 fixed row keys in display order
export const FIXED_ROW_KEYS = [
  'works', 'materials', 'transport', 'cleanup', 'overhead',
  'daily_workers', 'bank_guarantee', 'cleaning', 'ppr', 'commissioning',
  'construction_control', 'author_supervision', 'passes', 'site_office',
  'travel', 'rp', 'housing_rent', 'workers_transport',
] as const

export const DEFAULT_OVERRIDES: SummaryOverrides = {
  coefficient: 1.0,
  transport_pct: 3.0,
  cleanup_pct: 3.0,
  overhead_pct: 3.0,
  daily_workers_cost: 0,
  bank_guarantee_cost: 0,
  cleaning_cost: 0,
  ppr_cost: 0,
  commissioning_cost: 0,
  construction_control_cost: 0,
  author_supervision_cost: 0,
  passes_cost: 0,
  site_office_cost: 0,
  travel_cost: 0,
  rp_cost: 0,
  housing_rent_cost: 0,
  workers_transport_cost: 0,
  contingency_pct: 2.0,
  profit_pct: 20.0,
  vat_full_cost_pct: 22.0,
  tax_pct: 2.0,
  hidden_fixed_rows: [],
  custom_rows_before: [],
  custom_rows_after: [],
};

export interface SectionTab {
  card_id: string;
  card_name: string;
  version_id: string;
  version_display_name: string;
  rows: EstimateRow[];
  tax_pct?: number;
}

export interface SectionCalcRow {
  card_id: string;
  card_name: string;
  tax_pct: number;
  works_raw: number;
  materials_raw: number;
  works_with_vat: number;
  materials_with_vat: number;
}

export interface SummaryCalcResult {
  section_totals: SectionCalcRow[];

  // Rows 1–2
  works_with_vat: number;
  works_without_vat: number;
  materials_with_vat: number;
  materials_without_vat: number;

  // Rows 3–5
  transport_with_vat: number;
  transport_without_vat: number;
  cleanup_with_vat: number;
  cleanup_without_vat: number;
  overhead_with_vat: number;
  overhead_without_vat: number;

  // Row 6
  daily_workers_with_vat: number;
  daily_workers_without_vat: number;

  // Rows 7–18
  bank_guarantee_with_vat: number;
  bank_guarantee_without_vat: number;
  cleaning_with_vat: number;
  cleaning_without_vat: number;
  ppr_with_vat: number;
  ppr_without_vat: number;
  commissioning_with_vat: number;
  commissioning_without_vat: number;
  construction_control_with_vat: number;
  construction_control_without_vat: number;
  author_supervision_with_vat: number;
  author_supervision_without_vat: number;
  passes_with_vat: number;
  passes_without_vat: number;
  site_office_with_vat: number;
  site_office_without_vat: number;
  travel_with_vat: number;
  travel_without_vat: number;
  rp_with_vat: number;
  rp_without_vat: number;
  housing_rent_with_vat: number;
  housing_rent_without_vat: number;
  workers_transport_with_vat: number;
  workers_transport_without_vat: number;

  // Subtotal
  subtotal_with_vat: number;
  subtotal_without_vat: number;

  // Footer
  contingency_with_vat: number;
  contingency_without_vat: number;
  profit: number;
  full_cost_without_vat: number;
  vat: number;
  other_tax: number;
  total_for_customer: number;
}

export interface SummaryEstimate {
  id: string;
  project_id: string;
  sections: SectionTab[];
  overrides: SummaryOverrides;
  total_for_customer: number;
  created_at: string;
  updated_at: string;
}

export type SummaryEstimateResponse = SummaryEstimate;

export interface SectionInput {
  card_id: string;
  version_id: string;
}

export interface SummaryEstimateCreate {
  sections: SectionInput[];
  overrides?: Partial<SummaryOverrides>;
}

export interface SummaryEstimateUpdate {
  sections?: SectionTab[];
  overrides?: SummaryOverrides;
  total_for_customer?: number;
}
