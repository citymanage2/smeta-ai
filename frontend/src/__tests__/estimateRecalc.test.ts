import { describe, it, expect } from 'vitest';
import { applyWorkQuantityChange, buildNormComment } from '../utils/estimateRecalc';
import { EstimateRow } from '../types';

function work(id: string, qty: number | null = 10): EstimateRow {
  return {
    id,
    lineage_id: id,
    num: 1,
    type: 'work',
    name: 'Работа',
    unit: 'м²',
    qty,
    price_work: null,
    price_material: null,
    cost: null,
    selected: false,
  };
}

function material(
  id: string,
  workId: string,
  opts: Partial<EstimateRow> = {},
): EstimateRow {
  return {
    id,
    lineage_id: id,
    num: 2,
    type: 'material',
    name: 'Материал',
    unit: 'кг',
    qty: 50,
    price_work: null,
    price_material: null,
    cost: null,
    selected: false,
    work_row_id: workId,
    qty_per_work_unit: 5,
    ...opts,
  };
}

// ── applyWorkQuantityChange ──────────────────────────────────────────────────

describe('applyWorkQuantityChange', () => {
  it('пересчитывает qty материала без qty_overridden', () => {
    const rows = [work('w1', 10), material('m1', 'w1', { qty: 50 })];
    const { rows: result } = applyWorkQuantityChange(rows, 'w1', 20);
    expect(result.find((r) => r.id === 'm1')!.qty).toBe(100); // 20 * 5
  });

  it('пересчитывает материал с qty_overridden=true и сохраняет qty_manual_backup', () => {
    const rows = [
      work('w1', 10),
      material('m1', 'w1', { qty: 45, qty_overridden: true, qty_manual_backup: null }),
    ];
    const { rows: result, overriddenIds } = applyWorkQuantityChange(rows, 'w1', 20);
    const mat = result.find((r) => r.id === 'm1')!;
    expect(mat.qty).toBe(100);
    expect(mat.qty_manual_backup).toBe(45);
    expect(overriddenIds).toContain('m1');
  });

  it('не перезатирает qty_manual_backup если он уже был задан', () => {
    const rows = [
      work('w1', 10),
      material('m1', 'w1', { qty: 60, qty_overridden: true, qty_manual_backup: 45 }),
    ];
    const { rows: result } = applyWorkQuantityChange(rows, 'w1', 30);
    expect(result.find((r) => r.id === 'm1')!.qty_manual_backup).toBe(45);
  });

  it('пропускает материалы без qty_per_work_unit', () => {
    const rows = [
      work('w1', 10),
      material('m1', 'w1', { qty_per_work_unit: null }),
    ];
    const { rows: result, recalcedIds } = applyWorkQuantityChange(rows, 'w1', 20);
    expect(result.find((r) => r.id === 'm1')!.qty).toBe(
      rows.find((r) => r.id === 'm1')!.qty,
    );
    expect(recalcedIds).not.toContain('m1');
  });

  it('пропускает материалы с другим work_row_id', () => {
    const rows = [work('w1'), work('w2'), material('m1', 'w2')];
    const { rows: result } = applyWorkQuantityChange(rows, 'w1', 100);
    expect(result.find((r) => r.id === 'm1')!.qty).toBe(50);
  });
});

// ── buildNormComment ─────────────────────────────────────────────────────────

describe('buildNormComment', () => {
  it('формирует «авто: 50 кг (норм. 0.5 на м²)»', () => {
    const row = material('m1', 'w1', { qty: 50, qty_per_work_unit: 0.5 });
    expect(buildNormComment(row, 'м²')).toBe('авто: 50 кг (норм. 0.5 на м²)');
  });

  it('возвращает «задано вручную» при qty_overridden=true', () => {
    const row = material('m1', 'w1', { qty_overridden: true });
    expect(buildNormComment(row)).toBe('задано вручную');
  });

  it('при qty_per_work_unit=0 показывает «авто: 0 кг (норм. 0 на ед.)»', () => {
    const row = material('m1', 'w1', { qty: 0, qty_per_work_unit: 0 });
    expect(buildNormComment(row)).toBe('авто: 0 кг (норм. 0 на ед.)');
  });
});
