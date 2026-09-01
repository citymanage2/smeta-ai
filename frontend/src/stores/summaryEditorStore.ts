import { create } from 'zustand';
import {
  SectionTab,
  SummaryOverrides,
  SummaryCalcResult,
  SectionCalcRow,
  TargetBasis,
  TaxSide,
  DEFAULT_OVERRIDES,
} from '../types/summary';
import { getSummary, updateSummary } from '../api/summaryEstimate';
import { billableQty } from '../utils/negativeQty';
import { targetDeviation, targetValue } from '../utils/targets';

/**
 * Ставка налога половины раздела: у работ и материалов она своя.
 *
 * `tax_pct` — одна ставка на обе половины, как было раньше. Сводные, сохранённые
 * до раздельных налогов, лежат в базе именно так, поэтому она остаётся запасным
 * значением. То же правило на сервере — `_section_tax` в `utils/summary_calc.py`.
 */
export function sectionTaxPct(section: SectionTab, side: TaxSide): number {
  const own = side === 'works' ? section.tax_pct_works : section.tax_pct_materials;
  return Number(own ?? section.tax_pct ?? 0);
}

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
  const basis: TargetBasis = overrides.target_basis === 'with_vat' ? 'with_vat' : 'cost';
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
    const tax_pct_works = sectionTaxPct(sec, 'works');
    const tax_pct_materials = sectionTaxPct(sec, 'materials');
    const works_with_vat = works_raw * (1.22 - tax_pct_works / 100);
    const materials_with_vat = materials_raw * (1.22 - tax_pct_materials / 100);

    // Цели оптимизации: с чем сравнивать — решает база целей, одна на бланк.
    const target_works = targetValue(sec.target_works);
    const target_materials = targetValue(sec.target_materials);
    const works_fact = basis === 'cost' ? works_raw : works_with_vat;
    const materials_fact = basis === 'cost' ? materials_raw : materials_with_vat;
    const worksDev = targetDeviation(works_fact, target_works);
    const materialsDev = targetDeviation(materials_fact, target_materials);

    return {
      card_id: sec.card_id,
      card_name: sec.card_name,
      tax_pct_works,
      tax_pct_materials,
      works_raw,
      materials_raw,
      works_with_vat,
      materials_with_vat,
      target_works,
      target_materials,
      works_fact,
      materials_fact,
      works_deviation: worksDev.value,
      works_deviation_pct: worksDev.pct,
      materials_deviation: materialsDev.value,
      materials_deviation_pct: materialsDev.pct,
    };
  });

  // ── Цели: ИТОГО по разделам, у которых цель задана ────────────────────────
  const sideTotals = (side: 'works' | 'materials') => {
    const withTarget = section_totals.filter((s) => s[`target_${side}`] !== null);
    if (withTarget.length === 0) {
      return { total: null, fact: null, dev: null, pct: null };
    }
    const total = withTarget.reduce((sum, s) => sum + (s[`target_${side}`] as number), 0);
    const fact = withTarget.reduce((sum, s) => sum + s[`${side}_fact`], 0);
    const { value: dev, pct } = targetDeviation(fact, total);
    return { total, fact, dev, pct };
  };
  const worksTargets = sideTotals('works');
  const materialsTargets = sideTotals('materials');

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

  const target_total_for_customer = targetValue(overrides.target_total_for_customer);
  const totalDev = targetDeviation(total_for_customer, target_total_for_customer);

  return {
    section_totals,
    target_basis: basis,
    has_section_targets: section_totals.some(
      (s) => s.target_works !== null || s.target_materials !== null,
    ),
    targets_total_works: worksTargets.total,
    targets_fact_works: worksTargets.fact,
    targets_deviation_works: worksTargets.dev,
    targets_deviation_works_pct: worksTargets.pct,
    targets_total_materials: materialsTargets.total,
    targets_fact_materials: materialsTargets.fact,
    targets_deviation_materials: materialsTargets.dev,
    targets_deviation_materials_pct: materialsTargets.pct,
    target_total_for_customer,
    total_deviation: totalDev.value,
    total_deviation_pct: totalDev.pct,
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

/**
 * Состояние страницы сводной.
 *
 * Строк разделов этот стор больше не правит: с Фазы 7 раздел — документ
 * (`kind='summary-section'`), и его строки пишет только «Применить» в едином
 * редакторе. Здесь остаётся то, что принадлежит бланку: настройки, налоги
 * разделов, итог — и перечитывание разделов после правки.
 */
interface SummaryEditorState {
  projectId: string | null;
  summaryId: string | null;
  sections: SectionTab[];
  summaryOverrides: SummaryOverrides;
  activeTabIndex: number;
  isDirty: boolean;

  loadSummary: (projectId: string) => Promise<void>;
  /** Перечитать строки разделов, не трогая несохранённые настройки бланка. */
  refreshSections: () => Promise<void>;
  updateSectionTaxPct: (sectionIndex: number, side: TaxSide, taxPct: number) => void;
  /** Цель раздела по работам или материалам; null — цель снята. */
  updateSectionTarget: (sectionIndex: number, side: TaxSide, target: number | null) => void;
  updateOverride: <K extends keyof SummaryOverrides>(key: K, value: SummaryOverrides[K]) => void;
  setActiveTabIndex: (index: number) => void;
  save: () => Promise<void>;
  reset: () => void;
}

export const useSummaryEditorStore = create<SummaryEditorState>((set, get) => ({
  projectId: null,
  summaryId: null,
  sections: [],
  summaryOverrides: { ...DEFAULT_OVERRIDES },
  activeTabIndex: 0,
  isDirty: false,

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
      target_basis: raw.target_basis === 'with_vat' ? 'with_vat' : 'cost',
      target_total_for_customer: targetValue(
        raw.target_total_for_customer === null
          || raw.target_total_for_customer === undefined
          || raw.target_total_for_customer === ''
          ? null
          : Number(raw.target_total_for_customer),
      ),
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

  refreshSections: async () => {
    const { projectId, summaryOverrides, isDirty, sections: local } = get();
    if (!projectId) return;
    const summary = await getSummary(projectId);
    // С сервера берём только строки. Налог раздела и настройки бланка человек
    // мог поменять и ещё не сохранить — перечитывание не должно их стирать.
    const merged = summary.sections.map((remote) => {
      const mine = local.find((section) => section.card_id === remote.card_id);
      return mine
        ? {
            ...remote,
            tax_pct: mine.tax_pct,
            tax_pct_works: mine.tax_pct_works,
            tax_pct_materials: mine.tax_pct_materials,
            // Цель — такая же несохранённая настройка бланка, как налог:
            // перечитывание строк не имеет права её стереть.
            target_works: mine.target_works,
            target_materials: mine.target_materials,
          }
        : remote;
    });
    set({ sections: merged });

    if (isDirty) return;
    // Итог показывается на карточке проекта, а считает его только `calcSummary`.
    // Поэтому после правки строк сохраняем пересчитанное значение сразу — иначе
    // карточка держала бы старую сумму до следующего «Сохранить».
    const calc = calcSummary(summary.sections, summaryOverrides);
    await updateSummary(projectId, {
      sections: summary.sections,
      overrides: summaryOverrides,
      total_for_customer: calc.total_for_customer,
    });
  },

  updateSectionTaxPct: (sectionIndex: number, side: TaxSide, taxPct: number) => {
    const { sections } = get();
    const newSections = sections.map((sec, i) => {
      if (i !== sectionIndex) return sec;
      // Пишем обе ставки: вторую — её текущим действующим значением. Так у
      // тронутого раздела обе половины заданы явно, и старое поле `tax_pct`
      // больше не участвует в его расчёте — читать нечего, кроме своих ставок.
      return {
        ...sec,
        tax_pct_works: side === 'works' ? taxPct : sectionTaxPct(sec, 'works'),
        tax_pct_materials: side === 'materials' ? taxPct : sectionTaxPct(sec, 'materials'),
      };
    });
    set({ sections: newSections, isDirty: true });
  },

  updateSectionTarget: (sectionIndex: number, side: TaxSide, target: number | null) => {
    const { sections } = get();
    const key = side === 'works' ? 'target_works' : 'target_materials';
    set({
      sections: sections.map((sec, i) => (
        i === sectionIndex ? { ...sec, [key]: targetValue(target) } : sec
      )),
      isDirty: true,
    });
  },

  updateOverride: <K extends keyof SummaryOverrides>(key: K, value: SummaryOverrides[K]) => {
    const { summaryOverrides } = get();
    set({
      summaryOverrides: { ...summaryOverrides, [key]: value },
      isDirty: true,
    });
  },

  setActiveTabIndex: (index: number) => {
    set({ activeTabIndex: index });
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

  reset: () =>
    set({
      projectId: null,
      summaryId: null,
      sections: [],
      summaryOverrides: { ...DEFAULT_OVERRIDES },
      activeTabIndex: 0,
      isDirty: false,
    }),
}));
