import { EstimateRow } from './index';

export interface SummaryOverrides {
  coefficient: number;
  transport_pct: number;
  cleanup_pct: number;
  overhead_pct: number;
  daily_workers_cost: number;       // stores COUNT of workers (×5000 = cost)
  bank_guarantee_cost: number;      // stored as без НДС
  cleaning_cost: number;            // stored as без НДС
  ppr_cost: number;                 // stored as без НДС
  commissioning_cost: number;       // stored as без НДС (row 10: Разнорабочие мусор)
  construction_control_cost: number; // stored as без НДС
  author_supervision_cost: number;  // stored as без НДС
  passes_cost: number;              // stored as без НДС
  site_office_cost: number;         // stored as без НДС
  travel_cost: number;              // stored as без НДС
  rp_cost: number;                  // stored as без НДС
  housing_rent_cost: number;        // stored as без НДС
  workers_transport_cost: number;   // stored as без НДС
  contingency_pct: number;
  profit_pct: number;
  vat_full_cost_pct: number;        // НДС от полной себестоимости
  tax_pct: number;                  // Др. налоги от полной себестоимости
  // legacy (kept for backward compat, unused in calc)
  vat_works_pct?: number;
  vat_materials_pct?: number;
}

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
  works_with_vat: number;      // works_raw × (1.22 − tax_pct/100)
  materials_with_vat: number;  // materials_raw × (1.22 − tax_pct/100)
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

  // Rows 7–18 (pairs: with / without VAT)
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

  // Footer (merged cells — single values)
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
