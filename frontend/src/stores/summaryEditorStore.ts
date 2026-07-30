import { create } from 'zustand';
import { EstimateRow } from '../types';
import {
  SectionTab,
  SummaryOverrides,
  SummaryCalcResult,
  SectionCalcRow,
  DEFAULT_OVERRIDES,
} from '../types/summary';
import { getSummary, updateSummary } from '../api/summaryEstimate';
import { billableQty } from '../utils/negativeQty';

const MAX_HISTORY = 50;

function rowAmount(value: number | null, qty: number | null): number {
  // billableQty: строка с отрицательным объёмом — вычет, а не работа. Считать
  // по ней стоимость нельзя, иначе сводная занижается на qty × цену.
  return (value ?? 0) * billableQty(qty);
}

export function calcSummary(
  sections: SectionTab[],
  overrides: SummaryOverrides,
): SummaryCalcResult {
  const coeff = overrides.coefficient ?? 1.0;
  const toWithout = (v: number) => v / 1.22;
  const toWith = (v: number) => v * 1.22;
  const hidden = new Set(overrides.hidden_fixed_rows ?? []);

  // ── Section breakdown ──────────────────────────────────────────────────────
  const section_totals: SectionCalcRow[] = sections.map((sec) => {
    let works_raw = 0;
    let materials_raw = 0;
    for (const row of sec.rows) {
      if (row.type === 'section') continue;
      works_raw += rowAmount(row.price_work, row.qty);
      materials_raw += rowAmount(row.price_material, row.qty);
    }
    works_raw *= coeff;
    materials_raw *= coeff;
    const tax_pct = sec.tax_pct ?? 0;
    const multiplier = 1.22 - tax_pct / 100;
    return {
      card_id: sec.card_id,
      card_name: sec.card_name,
      tax_pct,
      works_raw,
      materials_raw,
      works_with_vat: works_raw * multiplier,
      materials_with_vat: materials_raw * multiplier,
    };
  });

  // ── Fixed row values ───────────────────────────────────────────────────────
  const works_with_vat = section_totals.reduce((s, r) => s + r.works_with_vat, 0);
  const materials_with_vat = section_totals.reduce((s, r) => s + r.materials_with_vat, 0);

  const base_with_vat = works_with_vat + materials_with_vat;

  const transport_with_vat = base_with_vat * (overrides.transport_pct ?? 3) / 100;
  const cleanup_with_vat = base_with_vat * (overrides.cleanup_pct ?? 3) / 100;
  const overhead_with_vat = base_with_vat * (overrides.overhead_pct ?? 3) / 100;
  const daily_workers_with_vat = (overrides.daily_workers_cost ?? 0) * 5000;

  const bg_wout = overrides.bank_guarantee_cost ?? 0;
  const cl_wout = overrides.cleaning_cost ?? 0;
  const ppr_wout = overrides.ppr_cost ?? 0;
  const com_wout = overrides.commissioning_cost ?? 0;
  const cc_wout = overrides.construction_control_cost ?? 0;
  const as_wout = overrides.author_supervision_cost ?? 0;
  const pa_wout = overrides.passes_cost ?? 0;
  const so_wout = overrides.site_office_cost ?? 0;
  const tr_wout = overrides.travel_cost ?? 0;
  const rp_wout = overrides.rp_cost ?? 0;
  const hr_wout = overrides.housing_rent_cost ?? 0;
  const wt_wout = overrides.workers_transport_cost ?? 0;

  // ── Subtotal: only include non-hidden fixed rows + custom before rows ──────
  let subtotal_with_vat = 0;
  if (!hidden.has('works'))              subtotal_with_vat += works_with_vat;
  if (!hidden.has('materials'))          subtotal_with_vat += materials_with_vat;
  if (!hidden.has('transport'))          subtotal_with_vat += transport_with_vat;
  if (!hidden.has('cleanup'))            subtotal_with_vat += cleanup_with_vat;
  if (!hidden.has('overhead'))           subtotal_with_vat += overhead_with_vat;
  if (!hidden.has('daily_workers'))      subtotal_with_vat += daily_workers_with_vat;
  if (!hidden.has('bank_guarantee'))     subtotal_with_vat += toWith(bg_wout);
  if (!hidden.has('cleaning'))           subtotal_with_vat += toWith(cl_wout);
  if (!hidden.has('ppr'))                subtotal_with_vat += toWith(ppr_wout);
  if (!hidden.has('commissioning'))      subtotal_with_vat += toWith(com_wout);
  if (!hidden.has('construction_control')) subtotal_with_vat += toWith(cc_wout);
  if (!hidden.has('author_supervision')) subtotal_with_vat += toWith(as_wout);
  if (!hidden.has('passes'))             subtotal_with_vat += toWith(pa_wout);
  if (!hidden.has('site_office'))        subtotal_with_vat += toWith(so_wout);
  if (!hidden.has('travel'))             subtotal_with_vat += toWith(tr_wout);
  if (!hidden.has('rp'))                 subtotal_with_vat += toWith(rp_wout);
  if (!hidden.has('housing_rent'))       subtotal_with_vat += toWith(hr_wout);
  if (!hidden.has('workers_transport'))  subtotal_with_vat += toWith(wt_wout);

  // Custom rows before separator contribute to subtotal
  for (const cr of (overrides.custom_rows_before ?? [])) {
    subtotal_with_vat += cr.without_vat * 1.22;
  }

  const subtotal_without_vat = toWithout(subtotal_with_vat);

  // ── Footer ────────────────────────────────────────────────────────────────
  const contingency_pct = overrides.contingency_pct ?? 2;
  const profit_pct = overrides.profit_pct ?? 20;
  const vat_full_cost_pct = overrides.vat_full_cost_pct ?? 22;
  const other_tax_pct = overrides.tax_pct ?? 2;

  const contingency_with_vat = subtotal_with_vat * contingency_pct / 100;
  const contingency_without_vat = subtotal_without_vat * contingency_pct / 100;

  const profit =
    (profit_pct / 100) * (1 + contingency_pct / 100) * subtotal_without_vat /
    (1 - profit_pct / 100);

  const full_cost_without_vat = subtotal_without_vat + contingency_without_vat + profit;
  const vat = full_cost_without_vat * vat_full_cost_pct / 100;
  const other_tax = full_cost_without_vat * other_tax_pct / 100;
  const total_for_customer = full_cost_without_vat + vat + other_tax;

  return {
    section_totals,
    works_with_vat,
    works_without_vat: toWithout(works_with_vat),
    materials_with_vat,
    materials_without_vat: toWithout(materials_with_vat),
    transport_with_vat,
    transport_without_vat: toWithout(transport_with_vat),
    cleanup_with_vat,
    cleanup_without_vat: toWithout(cleanup_with_vat),
    overhead_with_vat,
    overhead_without_vat: toWithout(overhead_with_vat),
    daily_workers_with_vat,
    daily_workers_without_vat: toWithout(daily_workers_with_vat),
    bank_guarantee_without_vat: bg_wout,
    bank_guarantee_with_vat: toWith(bg_wout),
    cleaning_without_vat: cl_wout,
    cleaning_with_vat: toWith(cl_wout),
    ppr_without_vat: ppr_wout,
    ppr_with_vat: toWith(ppr_wout),
    commissioning_without_vat: com_wout,
    commissioning_with_vat: toWith(com_wout),
    construction_control_without_vat: cc_wout,
    construction_control_with_vat: toWith(cc_wout),
    author_supervision_without_vat: as_wout,
    author_supervision_with_vat: toWith(as_wout),
    passes_without_vat: pa_wout,
    passes_with_vat: toWith(pa_wout),
    site_office_without_vat: so_wout,
    site_office_with_vat: toWith(so_wout),
    travel_without_vat: tr_wout,
    travel_with_vat: toWith(tr_wout),
    rp_without_vat: rp_wout,
    rp_with_vat: toWith(rp_wout),
    housing_rent_without_vat: hr_wout,
    housing_rent_with_vat: toWith(hr_wout),
    workers_transport_without_vat: wt_wout,
    workers_transport_with_vat: toWith(wt_wout),
    subtotal_with_vat,
    subtotal_without_vat,
    contingency_with_vat,
    contingency_without_vat,
    profit,
    full_cost_without_vat,
    vat,
    other_tax,
    total_for_customer,
  };
}

interface SummaryEditorState {
  projectId: string | null;
  summaryId: string | null;
  sections: SectionTab[];
  summaryOverrides: SummaryOverrides;
  activeTabIndex: number;
  isDirty: boolean;
  undoStack: EstimateRow[][];
  redoStack: EstimateRow[][];

  loadSummary: (projectId: string) => Promise<void>;
  updateSectionRows: (sectionIndex: number, rows: EstimateRow[]) => void;
  updateSectionTaxPct: (sectionIndex: number, taxPct: number) => void;
  updateOverride: <K extends keyof SummaryOverrides>(key: K, value: SummaryOverrides[K]) => void;
  setActiveTabIndex: (index: number) => void;
  save: () => Promise<void>;
  undo: () => void;
  redo: () => void;
  reset: () => void;
}

export const useSummaryEditorStore = create<SummaryEditorState>((set, get) => ({
  projectId: null,
  summaryId: null,
  sections: [],
  summaryOverrides: { ...DEFAULT_OVERRIDES },
  activeTabIndex: 0,
  isDirty: false,
  undoStack: [],
  redoStack: [],

  loadSummary: async (projectId: string) => {
    const summary = await getSummary(projectId);
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const raw = summary.overrides as any as Record<string, unknown>;
    const n = (key: string, fallback: number) => Number(raw[key] ?? fallback);
    const overrides: SummaryOverrides = {
      coefficient: n('coefficient', DEFAULT_OVERRIDES.coefficient),
      transport_pct: n('transport_pct', DEFAULT_OVERRIDES.transport_pct),
      cleanup_pct: n('cleanup_pct', DEFAULT_OVERRIDES.cleanup_pct),
      overhead_pct: n('overhead_pct', DEFAULT_OVERRIDES.overhead_pct),
      daily_workers_cost: n('daily_workers_cost', DEFAULT_OVERRIDES.daily_workers_cost),
      bank_guarantee_cost: n('bank_guarantee_cost', DEFAULT_OVERRIDES.bank_guarantee_cost),
      cleaning_cost: n('cleaning_cost', DEFAULT_OVERRIDES.cleaning_cost),
      ppr_cost: n('ppr_cost', DEFAULT_OVERRIDES.ppr_cost),
      commissioning_cost: n('commissioning_cost', DEFAULT_OVERRIDES.commissioning_cost),
      construction_control_cost: n('construction_control_cost', DEFAULT_OVERRIDES.construction_control_cost),
      author_supervision_cost: n('author_supervision_cost', DEFAULT_OVERRIDES.author_supervision_cost),
      passes_cost: n('passes_cost', DEFAULT_OVERRIDES.passes_cost),
      site_office_cost: n('site_office_cost', DEFAULT_OVERRIDES.site_office_cost),
      travel_cost: n('travel_cost', DEFAULT_OVERRIDES.travel_cost),
      rp_cost: n('rp_cost', DEFAULT_OVERRIDES.rp_cost),
      housing_rent_cost: n('housing_rent_cost', DEFAULT_OVERRIDES.housing_rent_cost),
      workers_transport_cost: n('workers_transport_cost', DEFAULT_OVERRIDES.workers_transport_cost),
      contingency_pct: n('contingency_pct', DEFAULT_OVERRIDES.contingency_pct),
      profit_pct: n('profit_pct', DEFAULT_OVERRIDES.profit_pct),
      vat_full_cost_pct: n('vat_full_cost_pct', DEFAULT_OVERRIDES.vat_full_cost_pct),
      tax_pct: n('tax_pct', DEFAULT_OVERRIDES.tax_pct),
      hidden_fixed_rows: Array.isArray(raw.hidden_fixed_rows) ? (raw.hidden_fixed_rows as string[]) : [],
      custom_rows_before: Array.isArray(raw.custom_rows_before) ? (raw.custom_rows_before as import('../types/summary').CustomCostRow[]) : [],
      custom_rows_after: Array.isArray(raw.custom_rows_after) ? (raw.custom_rows_after as import('../types/summary').CustomCostRow[]) : [],
    };
    set({
      projectId,
      summaryId: summary.id,
      sections: summary.sections,
      summaryOverrides: overrides,
      activeTabIndex: summary.sections.length > 0 ? 0 : -1,
      isDirty: false,
      undoStack: [],
      redoStack: [],
    });

    // Auto-save total on first open so project card shows the sum immediately.
    if (!summary.total_for_customer) {
      const calc = calcSummary(summary.sections, overrides);
      await updateSummary(projectId, {
        sections: summary.sections,
        overrides,
        total_for_customer: calc.total_for_customer,
      });
    }
  },

  updateSectionRows: (sectionIndex: number, rows: EstimateRow[]) => {
    const { sections, activeTabIndex, undoStack } = get();
    const previousRows = sections[sectionIndex]?.rows ?? [];
    const newSections = sections.map((sec, i) =>
      i === sectionIndex ? { ...sec, rows } : sec,
    );
    if (sectionIndex === activeTabIndex) {
      set({
        sections: newSections,
        undoStack: [...undoStack.slice(-(MAX_HISTORY - 1)), previousRows],
        redoStack: [],
        isDirty: true,
      });
    } else {
      set({ sections: newSections, isDirty: true });
    }
  },

  updateSectionTaxPct: (sectionIndex: number, taxPct: number) => {
    const { sections } = get();
    const newSections = sections.map((sec, i) =>
      i === sectionIndex ? { ...sec, tax_pct: taxPct } : sec,
    );
    set({ sections: newSections, isDirty: true });
  },

  updateOverride: <K extends keyof SummaryOverrides>(key: K, value: SummaryOverrides[K]) => {
    const { summaryOverrides } = get();
    set({
      summaryOverrides: { ...summaryOverrides, [key]: value },
      isDirty: true,
    });
  },

  setActiveTabIndex: (index: number) => {
    set({ activeTabIndex: index, undoStack: [], redoStack: [] });
  },

  save: async () => {
    const { projectId, sections, summaryOverrides } = get();
    if (!projectId) return;
    const calc = calcSummary(sections, summaryOverrides);
    const updated = await updateSummary(projectId, {
      sections,
      overrides: summaryOverrides,
      total_for_customer: calc.total_for_customer,
    });
    set({ summaryId: updated.id, isDirty: false });
  },

  undo: () => {
    const { undoStack, redoStack, sections, activeTabIndex } = get();
    if (undoStack.length === 0) return;
    const newUndoStack = [...undoStack];
    const previousRows = newUndoStack.pop()!;
    const currentRows = sections[activeTabIndex]?.rows ?? [];
    const newSections = sections.map((sec, i) =>
      i === activeTabIndex ? { ...sec, rows: previousRows } : sec,
    );
    set({
      undoStack: newUndoStack,
      redoStack: [currentRows, ...redoStack.slice(0, MAX_HISTORY - 1)],
      sections: newSections,
      isDirty: true,
    });
  },

  redo: () => {
    const { undoStack, redoStack, sections, activeTabIndex } = get();
    if (redoStack.length === 0) return;
    const newRedoStack = [...redoStack];
    const nextRows = newRedoStack.shift()!;
    const currentRows = sections[activeTabIndex]?.rows ?? [];
    const newSections = sections.map((sec, i) =>
      i === activeTabIndex ? { ...sec, rows: nextRows } : sec,
    );
    set({
      undoStack: [...undoStack.slice(-(MAX_HISTORY - 1)), currentRows],
      redoStack: newRedoStack,
      sections: newSections,
      isDirty: true,
    });
  },

  reset: () =>
    set({
      projectId: null,
      summaryId: null,
      sections: [],
      summaryOverrides: { ...DEFAULT_OVERRIDES },
      activeTabIndex: 0,
      isDirty: false,
      undoStack: [],
      redoStack: [],
    }),
}));
