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

const MAX_HISTORY = 50;

function rowAmount(value: number | null, qty: number | null): number {
  return (value ?? 0) * (qty ?? 0);
}

export function calcSummary(
  sections: SectionTab[],
  overrides: SummaryOverrides,
): SummaryCalcResult {
  let totalWorks = 0;
  let totalMaterials = 0;
  const coeff = overrides.coefficient ?? 1.0;

  const section_totals: SectionCalcRow[] = sections.map((sec) => {
    let works = 0;
    let materials = 0;
    for (const row of sec.rows) {
      if (row.type === 'section') continue;
      works += rowAmount(row.price_work, row.qty);
      materials += rowAmount(row.price_material, row.qty);
    }
    works *= coeff;
    materials *= coeff;
    totalWorks += works;
    totalMaterials += materials;

    const vat_works = (works * overrides.vat_works_pct) / 100;
    const vat_materials = (materials * overrides.vat_materials_pct) / 100;
    return {
      card_id: sec.card_id,
      card_name: sec.card_name,
      works,
      materials,
      vat_works,
      works_with_vat: works + vat_works,
      vat_materials,
      materials_with_vat: materials + vat_materials,
    };
  });

  const transport = (totalMaterials * overrides.transport_pct) / 100;
  const cleanup = (totalWorks * overrides.cleanup_pct) / 100;
  const overhead = (totalWorks * overrides.overhead_pct) / 100;
  const daily_workers = overrides.daily_workers_cost;
  const bank_guarantee = overrides.bank_guarantee_cost;
  const cleaning = overrides.cleaning_cost;
  const ppr = overrides.ppr_cost;
  const commissioning = overrides.commissioning_cost;

  const subtotal =
    totalWorks +
    totalMaterials +
    transport +
    cleanup +
    overhead +
    daily_workers +
    bank_guarantee +
    cleaning +
    ppr +
    commissioning;

  const contingency = (subtotal * overrides.contingency_pct) / 100;
  const profit = (subtotal * overrides.profit_pct) / 100;
  const full_cost = subtotal + contingency + profit;

  const vat =
    (totalWorks * overrides.vat_works_pct) / 100 +
    (totalMaterials * overrides.vat_materials_pct) / 100;
  const tax = (full_cost * overrides.tax_pct) / 100;
  const total_for_customer = full_cost + vat + tax;

  return {
    works: totalWorks,
    materials: totalMaterials,
    transport,
    cleanup,
    overhead,
    daily_workers,
    bank_guarantee,
    cleaning,
    ppr,
    commissioning,
    subtotal,
    contingency,
    profit,
    full_cost,
    vat,
    tax,
    total_for_customer,
    section_totals,
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
  updateOverride: <K extends keyof SummaryOverrides>(key: K, value: number) => void;
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
    const overrides: SummaryOverrides = {
      coefficient: Number(summary.overrides.coefficient ?? DEFAULT_OVERRIDES.coefficient),
      transport_pct: Number(summary.overrides.transport_pct ?? DEFAULT_OVERRIDES.transport_pct),
      cleanup_pct: Number(summary.overrides.cleanup_pct ?? DEFAULT_OVERRIDES.cleanup_pct),
      overhead_pct: Number(summary.overrides.overhead_pct ?? DEFAULT_OVERRIDES.overhead_pct),
      daily_workers_cost: Number(
        summary.overrides.daily_workers_cost ?? DEFAULT_OVERRIDES.daily_workers_cost,
      ),
      bank_guarantee_cost: Number(
        summary.overrides.bank_guarantee_cost ?? DEFAULT_OVERRIDES.bank_guarantee_cost,
      ),
      cleaning_cost: Number(summary.overrides.cleaning_cost ?? DEFAULT_OVERRIDES.cleaning_cost),
      ppr_cost: Number(summary.overrides.ppr_cost ?? DEFAULT_OVERRIDES.ppr_cost),
      commissioning_cost: Number(
        summary.overrides.commissioning_cost ?? DEFAULT_OVERRIDES.commissioning_cost,
      ),
      contingency_pct: Number(
        summary.overrides.contingency_pct ?? DEFAULT_OVERRIDES.contingency_pct,
      ),
      profit_pct: Number(summary.overrides.profit_pct ?? DEFAULT_OVERRIDES.profit_pct),
      vat_works_pct: Number(summary.overrides.vat_works_pct ?? DEFAULT_OVERRIDES.vat_works_pct),
      vat_materials_pct: Number(
        summary.overrides.vat_materials_pct ?? DEFAULT_OVERRIDES.vat_materials_pct,
      ),
      tax_pct: Number(summary.overrides.tax_pct ?? DEFAULT_OVERRIDES.tax_pct),
    };
    set({
      projectId,
      summaryId: summary.id,
      sections: summary.sections,
      summaryOverrides: overrides,
      activeTabIndex: 0,
      isDirty: false,
      undoStack: [],
      redoStack: [],
    });
  },

  updateSectionRows: (sectionIndex: number, rows: EstimateRow[]) => {
    const { sections, activeTabIndex, undoStack } = get();
    const previousRows = sections[sectionIndex]?.rows ?? [];
    const newSections = sections.map((sec, i) =>
      i === sectionIndex ? { ...sec, rows } : sec,
    );
    // Only track undo when editing the active section
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

  updateOverride: <K extends keyof SummaryOverrides>(key: K, value: number) => {
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
    set({
      summaryId: updated.id,
      isDirty: false,
    });
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
