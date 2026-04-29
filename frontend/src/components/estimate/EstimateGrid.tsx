import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import DataGrid, { Column, SelectColumn, RenderEditCellProps, RenderCellProps, RenderRowProps, RowsChangeData, Row } from 'react-data-grid';
import 'react-data-grid/lib/styles.css';
import './EstimateGrid.css';
import { EstimateRow } from '../../types';

type GridTab = 'all' | 'works' | 'materials';

interface EstimateGridProps {
  rows: EstimateRow[];
  selectedRowIds: ReadonlySet<string>;
  activeTab: GridTab;
  isReadonly?: boolean;
  canUndo?: boolean;
  canRedo?: boolean;
  onRowsChange: (rows: EstimateRow[]) => void;
  onSelectedRowIdsChange: (ids: ReadonlySet<string>) => void;
  onTabChange: (tab: GridTab) => void;
  onSave: () => Promise<void>;
  onUndo?: () => void;
  onRedo?: () => void;
}

const fmt = (n: number) => Math.round(n).toLocaleString('ru-RU');

const calcCost = (row: EstimateRow): number =>
  (row.qty ?? 0) * ((row.price_work ?? 0) + (row.price_material ?? 0));

function NumberEditor({ row, column, onRowChange }: RenderEditCellProps<EstimateRow>) {
  const key = column.key as keyof EstimateRow;
  const raw = row[key] as number | null;
  const inputRef = useRef<HTMLInputElement>(null);

  const commit = useCallback(() => {
    const val = inputRef.current?.value ?? '';
    const parsed = val === '' ? null : parseFloat(val);
    const updated = { ...row, [key]: parsed };
    updated.cost = calcCost(updated);
    onRowChange(updated, true);
  }, [row, key, onRowChange]);

  const cancel = useCallback(() => {
    // Restore original row — commits unchanged value, effectively a no-op
    onRowChange(row, true);
  }, [row, onRowChange]);

  return (
    <div className="cell-editor-wrap">
      <input
        ref={inputRef}
        type="number"
        min="0"
        step="0.01"
        defaultValue={raw ?? ''}
        autoFocus
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit(); }
          if (e.key === 'Escape') { e.preventDefault(); cancel(); }
        }}
        className="cell-editor-input cell-editor-input-right"
      />
      <button
        className="cell-editor-confirm"
        title="Подтвердить (Enter)"
        onMouseDown={(e) => e.preventDefault()}
        onClick={commit}
      >✓</button>
      <button
        className="cell-editor-cancel"
        title="Отменить (Esc)"
        onMouseDown={(e) => e.preventDefault()}
        onClick={cancel}
      >✕</button>
    </div>
  );
}

function ConfirmTextEditor({ row, column, onRowChange }: RenderEditCellProps<EstimateRow>) {
  const key = column.key as keyof EstimateRow;
  const raw = String(row[key] ?? '');
  const inputRef = useRef<HTMLInputElement>(null);

  const commit = useCallback(() => {
    const val = inputRef.current?.value ?? '';
    onRowChange({ ...row, [key]: val }, true);
  }, [row, key, onRowChange]);

  const cancel = useCallback(() => {
    onRowChange(row, true);
  }, [row, onRowChange]);

  return (
    <div className="cell-editor-wrap">
      <input
        ref={inputRef}
        type="text"
        defaultValue={raw}
        autoFocus
        onKeyDown={(e) => {
          if (e.key === 'Enter') { e.preventDefault(); commit(); }
          if (e.key === 'Escape') { e.preventDefault(); cancel(); }
        }}
        className="cell-editor-input"
      />
      <button
        className="cell-editor-confirm"
        title="Подтвердить (Enter)"
        onMouseDown={(e) => e.preventDefault()}
        onClick={commit}
      >✓</button>
      <button
        className="cell-editor-cancel"
        title="Отменить (Esc)"
        onMouseDown={(e) => e.preventDefault()}
        onClick={cancel}
      >✕</button>
    </div>
  );
}

function CostCell({ row }: RenderCellProps<EstimateRow>) {
  const cost = calcCost(row);
  return <span className="cell-cost">{cost > 0 ? fmt(cost) : '—'}</span>;
}

function CommentCell({ row }: RenderCellProps<EstimateRow>) {
  const note = row.optimization_note;
  if (!note) return null;
  return <span className="cell-comment" title={note}>{note}</span>;
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
    renderEditCell: ConfirmTextEditor,
    editable: (row) => row.type !== 'section',
  },
  {
    key: 'unit',
    name: 'Ед. изм.',
    width: 80,
    renderEditCell: ConfirmTextEditor,
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

const COMMENT_COL: Column<EstimateRow> = {
  key: 'optimization_note',
  name: 'Комментарий',
  width: 260,
  renderCell: CommentCell,
};

const ALL_COLUMNS: Column<EstimateRow>[] = [
  SelectColumn,
  ...BASE_COLUMNS,
  WORK_PRICE_COL,
  MATERIAL_PRICE_COL,
  COST_COL,
  COMMENT_COL,
];

const WORKS_COLUMNS: Column<EstimateRow>[] = [
  SelectColumn,
  ...BASE_COLUMNS,
  WORK_PRICE_COL,
  COST_COL,
  COMMENT_COL,
];

const MATERIALS_COLUMNS: Column<EstimateRow>[] = [
  SelectColumn,
  ...BASE_COLUMNS,
  MATERIAL_PRICE_COL,
  COST_COL,
  COMMENT_COL,
];

const SAVE_DEBOUNCE_MS = 500;

type SaveStatus = 'idle' | 'saving' | 'saved';

const EstimateGrid: React.FC<EstimateGridProps> = ({
  rows,
  selectedRowIds,
  activeTab,
  isReadonly = false,
  canUndo = false,
  canRedo = false,
  onRowsChange,
  onSelectedRowIdsChange,
  onTabChange,
  onSave,
  onUndo,
  onRedo,
}) => {
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle');
  const [showOnlyAdded, setShowOnlyAdded] = useState(false);

  const displayedRows = useMemo(() => {
    let filtered = rows;
    if (showOnlyAdded) filtered = filtered.filter((r) => r.optimization_note != null);
    if (activeTab === 'works') return filtered.filter((r) => r.type === 'work');
    if (activeTab === 'materials') return filtered.filter((r) => r.type === 'material');
    return filtered;
  }, [rows, activeTab, showOnlyAdded]);

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

  const handleUnfilledClick = useCallback(() => {
    setShowOnlyAdded(true);
  }, []);

  const rowKeyGetter = useCallback((row: EstimateRow) => row.id, []);

  const rowClass = useCallback(
    (row: EstimateRow) => {
      if (row.is_excluded) return 'row-excluded';
      if (row.optimization_confidence) return `row-proposal-${row.optimization_confidence}`;
      if (
        row.type !== 'section' &&
        row.optimization_note != null &&
        (row.price_work == null || row.price_material == null)
      )
        return 'row-unfilled';
      return undefined;
    },
    [],
  );

  const renderRow = useCallback(
    (key: React.Key, props: RenderRowProps<EstimateRow>) => {
      if (props.row.type !== 'section') {
        return <Row key={key} {...props} />;
      }
      return (
        <div
          key={key}
          role="row"
          aria-rowindex={props.rowIdx + 2}
          style={{ display: 'contents', '--rdg-grid-row-start': props.gridRowStart } as React.CSSProperties}
        >
          <div className="section-header-cell">
            {props.row.name}
          </div>
        </div>
      );
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
          {/* Undo / Redo */}
          <div className="estimate-grid-history-btns">
            <button
              className="estimate-grid-history-btn"
              disabled={!canUndo || isReadonly}
              onClick={onUndo}
              title="Отменить изменение"
            >↩</button>
            <button
              className="estimate-grid-history-btn"
              disabled={!canRedo || isReadonly}
              onClick={onRedo}
              title="Вернуть изменение"
            >↪</button>
          </div>
          {saveStatusLabel && (
            <span className={`estimate-grid-save-status ${saveStatus}`}>{saveStatusLabel}</span>
          )}
        </div>
      </div>

      {/* Unfilled warning */}
      {unfilledCount > 0 && !showOnlyAdded && (
        <div className="estimate-grid-warning" onClick={handleUnfilledClick}>
          ⚠ {unfilledCount} {unfilledCount === 1 ? 'позиция требует' : 'позиции требуют'} заполнения цены — нажмите, чтобы перейти
        </div>
      )}

      {/* Added-only filter active */}
      {showOnlyAdded && (
        <div className="estimate-grid-filter-active">
          <span>Показаны только добавленные позиции ({displayedRows.length})</span>
          <button className="estimate-grid-filter-reset" onClick={() => setShowOnlyAdded(false)}>
            Показать всю смету
          </button>
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
        renderers={{ renderRow }}
        style={{ blockSize: 'auto', minHeight: 300, maxHeight: 600 }}
        enableVirtualization
      />
    </div>
  );
};

export default EstimateGrid;
