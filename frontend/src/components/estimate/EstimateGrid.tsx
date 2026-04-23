import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { DataGrid, Column, SelectColumn, RenderEditCellProps, RenderCellProps, RowsChangeData, renderTextEditor } from 'react-data-grid';
import 'react-data-grid/lib/styles.css';
import './EstimateGrid.css';
import { EstimateRow } from '../../types';

type GridTab = 'all' | 'works' | 'materials';

interface EstimateGridProps {
  rows: EstimateRow[];
  selectedRowIds: ReadonlySet<string>;
  activeTab: GridTab;
  isReadonly?: boolean;
  onRowsChange: (rows: EstimateRow[]) => void;
  onSelectedRowIdsChange: (ids: ReadonlySet<string>) => void;
  onTabChange: (tab: GridTab) => void;
  onSave: () => Promise<void>;
}

const fmt = (n: number) => Math.round(n).toLocaleString('ru-RU');

const calcCost = (row: EstimateRow): number =>
  (row.qty ?? 0) * ((row.price_work ?? 0) + (row.price_material ?? 0));

function NumberEditor({ row, column, onRowChange }: RenderEditCellProps<EstimateRow>) {
  const key = column.key as keyof EstimateRow;
  const raw = row[key] as number | null;
  return (
    <input
      type="number"
      min="0"
      step="0.01"
      defaultValue={raw ?? ''}
      autoFocus
      onBlur={(e) => {
        const val = e.target.value === '' ? null : parseFloat(e.target.value);
        const updated = { ...row, [key]: val };
        updated.cost = calcCost(updated);
        onRowChange(updated, true);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === 'Tab') {
          const val = (e.target as HTMLInputElement).value;
          const parsed = val === '' ? null : parseFloat(val);
          const updated = { ...row, [key]: parsed };
          updated.cost = calcCost(updated);
          onRowChange(updated, true);
        }
      }}
      style={{
        width: '100%',
        height: '100%',
        border: 'none',
        outline: 'none',
        padding: '0 8px',
        fontSize: '13px',
        fontFamily: 'inherit',
        textAlign: 'right',
        background: '#fff',
      }}
    />
  );
}

function CostCell({ row }: RenderCellProps<EstimateRow>) {
  const cost = calcCost(row);
  return <span className="cell-cost">{cost > 0 ? fmt(cost) : '—'}</span>;
}

function TypeBadgeCell({ row }: RenderCellProps<EstimateRow>) {
  const map: Record<string, string> = {
    work: 'Работа',
    material: 'Материал',
    section: 'Раздел',
  };
  const cls: Record<string, string> = {
    work: 'type-badge type-badge-work',
    material: 'type-badge type-badge-material',
    section: 'type-badge type-badge-section',
  };
  return <span className={cls[row.type] ?? 'type-badge'}>{map[row.type] ?? row.type}</span>;
}

function NumericCell({ row, column }: RenderCellProps<EstimateRow>) {
  const key = column.key as keyof EstimateRow;
  const val = row[key] as number | null;
  return <span className="cell-number">{val != null ? fmt(val) : '—'}</span>;
}

const BASE_COLUMNS: Column<EstimateRow>[] = [
  { key: 'num', name: '№', width: 50, frozen: true, renderCell: NumericCell },
  { key: 'type', name: 'Тип', width: 90, renderCell: TypeBadgeCell },
  {
    key: 'name',
    name: 'Наименование',
    width: 340,
    renderEditCell: renderTextEditor,
    editable: (row) => row.type !== 'section',
  },
  {
    key: 'unit',
    name: 'Ед. изм.',
    width: 80,
    renderEditCell: renderTextEditor,
    editable: (row) => row.type !== 'section',
  },
  {
    key: 'qty',
    name: 'Кол-во',
    width: 80,
    renderEditCell: NumberEditor,
    renderCell: NumericCell,
    editable: (row) => row.type !== 'section',
  },
];

const WORK_PRICE_COL: Column<EstimateRow> = {
  key: 'price_work',
  name: 'Цена работы, руб',
  width: 140,
  renderEditCell: NumberEditor,
  renderCell: NumericCell,
  editable: (row) => row.type !== 'section',
};

const MATERIAL_PRICE_COL: Column<EstimateRow> = {
  key: 'price_material',
  name: 'Цена материала, руб',
  width: 155,
  renderEditCell: NumberEditor,
  renderCell: NumericCell,
  editable: (row) => row.type !== 'section',
};

const COST_COL: Column<EstimateRow> = {
  key: 'cost',
  name: 'Стоимость, руб',
  width: 140,
  renderCell: CostCell,
};

const ALL_COLUMNS: Column<EstimateRow>[] = [
  SelectColumn,
  ...BASE_COLUMNS,
  WORK_PRICE_COL,
  MATERIAL_PRICE_COL,
  COST_COL,
];

const WORKS_COLUMNS: Column<EstimateRow>[] = [
  SelectColumn,
  ...BASE_COLUMNS,
  WORK_PRICE_COL,
  COST_COL,
];

const MATERIALS_COLUMNS: Column<EstimateRow>[] = [
  SelectColumn,
  ...BASE_COLUMNS,
  MATERIAL_PRICE_COL,
  COST_COL,
];

const SAVE_DEBOUNCE_MS = 500;

type SaveStatus = 'idle' | 'saving' | 'saved';

const EstimateGrid: React.FC<EstimateGridProps> = ({
  rows,
  selectedRowIds,
  activeTab,
  isReadonly = false,
  onRowsChange,
  onSelectedRowIdsChange,
  onTabChange,
  onSave,
}) => {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');

  const displayedRows = useMemo(() => {
    if (activeTab === 'works') return rows.filter((r) => r.type === 'work');
    if (activeTab === 'materials') return rows.filter((r) => r.type === 'material');
    return rows;
  }, [rows, activeTab]);

  const unfilledCount = useMemo(
    () =>
      rows.filter(
        (r) =>
          (r.type === 'work' || r.type === 'material') &&
          r.optimization_note != null &&
          (r.price_work == null || r.price_material == null),
      ).length,
    [rows],
  );

  const columns = useMemo(() => {
    const cols =
      activeTab === 'works'
        ? WORKS_COLUMNS
        : activeTab === 'materials'
          ? MATERIALS_COLUMNS
          : ALL_COLUMNS;

    if (isReadonly) {
      return cols.map((c) => ({ ...c, editable: false, renderEditCell: undefined }));
    }
    return cols;
  }, [activeTab, isReadonly]);

  const triggerSave = useCallback(() => {
    setSaveStatus('saving');
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      await onSave();
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    }, SAVE_DEBOUNCE_MS);
  }, [onSave]);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const handleRowsChange = useCallback(
    (newDisplayed: EstimateRow[], { indexes }: RowsChangeData<EstimateRow>) => {
      const changedIds = new Set(indexes.map((i) => newDisplayed[i].id));
      const changedMap = new Map(
        newDisplayed.filter((r) => changedIds.has(r.id)).map((r) => [r.id, r]),
      );
      const merged = rows.map((r) => {
        const updated = changedMap.get(r.id);
        if (!updated) return r;
        return { ...updated, cost: calcCost(updated) };
      });
      onRowsChange(merged);
      triggerSave();
    },
    [rows, onRowsChange, triggerSave],
  );

  const scrollToFirstUnfilled = useCallback(() => {
    const first = rows.find(
      (r) =>
        (r.type === 'work' || r.type === 'material') &&
        r.optimization_note != null &&
        (r.price_work == null || r.price_material == null),
    );
    if (!first) return;
    const el = document.querySelector(`[data-row-key="${first.id}"]`);
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [rows]);

  const rowKeyGetter = useCallback((row: EstimateRow) => row.id, []);

  const rowClass = useCallback(
    (row: EstimateRow) => {
      if (row.type === 'section') return 'row-section';
      if (
        row.optimization_note != null &&
        (row.price_work == null || row.price_material == null)
      )
        return 'row-unfilled';
      return undefined;
    },
    [],
  );

  const saveStatusLabel =
    saveStatus === 'saving'
      ? 'Сохранение...'
      : saveStatus === 'saved'
        ? 'Сохранено'
        : '';

  return (
    <div className="estimate-grid-wrapper">
      {/* Tab row */}
      <div className="estimate-grid-tabs">
        {(['all', 'works', 'materials'] as GridTab[]).map((tab) => (
          <button
            key={tab}
            className={`estimate-grid-tab${activeTab === tab ? ' active' : ''}`}
            onClick={() => onTabChange(tab)}
          >
            {tab === 'all' ? 'Полный перечень' : tab === 'works' ? 'Работы' : 'Материалы'}
          </button>
        ))}
      </div>

      {/* Header bar */}
      <div className="estimate-grid-header">
        <div style={{ fontSize: '13px', color: '#64748b' }}>
          Строк: {displayedRows.length}
          {selectedRowIds.size > 0 && (
            <span style={{ marginLeft: 10, color: '#2563eb', fontWeight: 600 }}>
              Выбрано: {selectedRowIds.size}
            </span>
          )}
        </div>
        <div className="estimate-grid-actions">
          {saveStatusLabel && (
            <span className={`estimate-grid-save-status ${saveStatus}`}>{saveStatusLabel}</span>
          )}
        </div>
      </div>

      {/* Unfilled warning */}
      {unfilledCount > 0 && (
        <div className="estimate-grid-warning" onClick={scrollToFirstUnfilled}>
          ⚠ {unfilledCount} {unfilledCount === 1 ? 'позиция требует' : 'позиции требуют'} заполнения цены — нажмите, чтобы перейти
        </div>
      )}

      {/* Optimization running banner */}
      {isReadonly && (
        <div className="estimate-grid-banner">
          <div className="estimate-grid-banner-text">
            <span>⏳</span>
            <span>Анализ выполняется в фоне — редактирование недоступно. Вы можете закрыть страницу, результаты сохранятся.</span>
          </div>
        </div>
      )}

      {/* Grid */}
      <DataGrid
        columns={columns}
        rows={displayedRows}
        onRowsChange={handleRowsChange}
        rowKeyGetter={rowKeyGetter}
        selectedRows={selectedRowIds}
        onSelectedRowsChange={onSelectedRowIdsChange}
        rowClass={rowClass}
        style={{ blockSize: 'auto', minHeight: 300, maxHeight: 600 }}
        enableVirtualization
      />
    </div>
  );
};

export default EstimateGrid;
