import { EstimateRow } from './index';

export interface SummaryOverrides {
  transport_pct: number;
  cleanup_pct: number;
  overhead_pct: number;
  daily_workers_cost: number;
  bank_guarantee_cost: number;
  cleaning_cost: number;
  ppr_cost: number;
  commissioning_cost: number;
  contingency_pct: number;
  profit_pct: number;
  vat_works_pct: number;
  vat_materials_pct: number;
  tax_pct: number;
}

export const DEFAULT_OVERRIDES: SummaryOverrides = {
  transport_pct: 1.0,
  cleanup_pct: 1.5,
  overhead_pct: 2.0,
  daily_workers_cost: 0,
  bank_guarantee_cost: 0,
  cleaning_cost: 0,
  ppr_cost: 0,
  commissioning_cost: 0,
  contingency_pct: 2.0,
  profit_pct: 16.0,
  vat_works_pct: 22.0,
  vat_materials_pct: 20.0,
  tax_pct: 3.0,
};

export interface SectionTab {
  card_id: string;
  card_name: string;
  version_id: string;
  version_display_name: string;
  rows: EstimateRow[];
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

export interface SectionCalcRow {
  card_id: string;
  card_name: string;
  works: number;
  materials: number;
  vat_works: number;
  works_with_vat: number;
  vat_materials: number;
  materials_with_vat: number;
}

export interface SummaryCalcResult {
  works: number;
  materials: number;
  transport: number;
  cleanup: number;
  overhead: number;
  daily_workers: number;
  bank_guarantee: number;
  cleaning: number;
  ppr: number;
  commissioning: number;
  subtotal: number;
  contingency: number;
  profit: number;
  full_cost: number;
  vat: number;
  tax: number;
  total_for_customer: number;
  section_totals: SectionCalcRow[];
}
