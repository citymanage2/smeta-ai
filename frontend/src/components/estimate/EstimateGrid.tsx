import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import DataGrid, {
  Column,
  SelectColumn,
  RenderEditCellProps,
  RenderCellProps,
  RenderRowProps,
  RowsChangeData,
  Row,
} from 'react-data-grid';
import 'react-data-grid/lib/styles.css';
import './EstimateGrid.css';
import { EstimateRow } from '../../types';
import { applyWorkQuantityChange, buildNormComment } from '../../utils/estimateRecalc';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

interface ToastItem {
  id: number;
  message: string;
  action?: { label: string; onClick: () => void };
}

// ---------------------------------------------------------------------------
// Context — позволяет QtyCell обращаться к актуальным rows и callbacks
// без стейл-замыканий в колонках
// ---------------------------------------------------------------------------

interface GridContextValue {
  rowsRef: React.MutableRefObject<EstimateRow[]>;
  displayedRowsRef: React.MutableRefObject<EstimateRow[]>;
  isReadonly: boolean;
  onQtyRestore: (rowId: string) => void;
  onTypeChange: (rowId: string, newType: EstimateRow['type']) => void;
  onDragRowStart: (rowId: string, e: React.DragEvent) => void;
  onDragRowEnd: () => void;
}

const GridContext = createContext<GridContextValue>({
  rowsRef: { current: [] },
  displayedRowsRef: { current: [] },
  isReadonly: false,
  onQtyRestore: () => {},
  onTypeChange: () => {},
  onDragRowStart: () => {},
  onDragRowEnd: () => {},
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const fmt = (n: number) => Math.round(n).toLocaleString('ru-RU');

const calcCost = (row: EstimateRow): number =>
  (row.qty ?? 0) * ((row.price_work ?? 0) + (row.price_material ?? 0));

// ---------------------------------------------------------------------------
// Cell editors
// ---------------------------------------------------------------------------

function NumberEditor({ row, column, onRowChange }: RenderEditCellProps<EstimateRow>) {
  const key = column.key as keyof EstimateRow;
  const raw = row[key] as number | null;
  const inputRef = useRef<HTMLInputElement>(null);

  const commit = useCallback(() => {
    const val = inputRef.current?.value ?? '';
    const parsed = val === '' ? null : parseFloat(val.replace(',', '.'));
    const updated: EstimateRow = { ...row, [key]: parsed };
    // Помечаем ручное изменение qty материала
    if (key === 'qty' && row.type === 'material') {
      updated.qty_overridden = true;
    }
    updated.cost = calcCost(updated);
    onRowChange(updated, true);
  }, [row, key, onRowChange]);

  const cancel = useCallback(() => {
    onRowChange(row, true);
  }, [row, onRowChange]);

  return (
    <div className="cell-editor-wrap">
      <input
        ref={inputRef}
        type="text"
        inputMode="decimal"
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

// ---------------------------------------------------------------------------
// Cell renderers
// ---------------------------------------------------------------------------

function CostCell({ row }: RenderCellProps<EstimateRow>) {
  const cost = calcCost(row);
  return <span className="cell-cost">{cost > 0 ? fmt(cost) : '—'}</span>;
}

function CommentCell({ row }: RenderCellProps<EstimateRow>) {
  const note = row.optimization_note;
  if (!note) return null;
  return <span className="cell-comment" title={note}>{note}</span>;
}

const TYPE_LABELS: Record<string, string> = {
  work: 'Р',
  material: 'М',
  section: 'Раздел',
};
const TYPE_LABELS_FULL: Record<string, string> = {
  work: 'Работа',
  material: 'Материал',
  section: 'Раздел',
};
const TYPE_CLASSES: Record<string, string> = {
  work: 'type-badge type-badge-work',
  material: 'type-badge type-badge-material',
  section: 'type-badge type-badge-section',
};

function TypeCell({ row }: RenderCellProps<EstimateRow>) {
  const { isReadonly, onTypeChange } = useContext(GridContext);
  const [open, setOpen] = useState(false);
  const selectRef = useRef<HTMLSelectElement>(null);

  useEffect(() => {
    if (open) selectRef.current?.focus();
  }, [open]);

  if (open && !isReadonly) {
    return (
      <select
        ref={selectRef}
        className="type-editor-select"
        value={row.type}
        onChange={(e) => {
          onTypeChange(row.id, e.target.value as EstimateRow['type']);
          setOpen(false);
        }}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false); }}
      >
        <option value="work">Работа</option>
        <option value="material">Материал</option>
        <option value="section">Раздел</option>
      </select>
    );
  }

  return (
    <span
      className={`${TYPE_CLASSES[row.type] ?? 'type-badge'}${!isReadonly ? ' type-badge-clickable' : ''}`}
      onClick={() => { if (!isReadonly) setOpen(true); }}
      title={isReadonly ? (TYPE_LABELS_FULL[row.type] ?? row.type) : `${TYPE_LABELS_FULL[row.type] ?? row.type} — нажмите для изменения`}
    >
      {TYPE_LABELS[row.type] ?? row.type}
    </span>
  );
}

function DragHandleCell({ row }: RenderCellProps<EstimateRow>) {
  const { isReadonly, onDragRowStart, onDragRowEnd } = useContext(GridContext);
  if (isReadonly || row.type === 'section') return null;
  return (
    <div
      className="drag-handle-cell"
      draggable
      onDragStart={(e) => onDragRowStart(row.id, e)}
      onDragEnd={onDragRowEnd}
      title="Перетащите для перемещения строки"
    >
      <svg className="drag-handle-icon" viewBox="0 0 8 14" width="10" height="14" fill="currentColor">
        <circle cx="2" cy="2.5" r="1.2" /><circle cx="6" cy="2.5" r="1.2" />
        <circle cx="2" cy="7" r="1.2" /><circle cx="6" cy="7" r="1.2" />
        <circle cx="2" cy="11.5" r="1.2" /><circle cx="6" cy="11.5" r="1.2" />
      </svg>
    </div>
  );
}

function NumericCell({ row, column }: RenderCellProps<EstimateRow>) {
  const key = column.key as keyof EstimateRow;
  const val = row[key] as number | null;
  return <span className="cell-number">{val != null ? fmt(val) : '—'}</span>;
}

/**
 * QtyCell — специализированная ячейка для колонки «Кол-во».
 * Для материалов показывает norm-комментарий и кнопку ↩ возврата ручного объёма.
 */
function QtyCell({ row }: RenderCellProps<EstimateRow>) {
  const { rowsRef, onQtyRestore } = useContext(GridContext);

  const qty = row.qty;

  if (row.type !== 'material') {
    return <span className="cell-number">{qty != null ? fmt(qty) : '—'}</span>;
  }

  const currentRows = rowsRef.current;
  const workRow = row.work_row_id
    ? currentRows.find((r) => r.id === row.work_row_id)
    : null;

  const comment = buildNormComment(row, workRow?.unit);
  const showRestoreBtn = row.qty_manual_backup != null && workRow != null;

  return (
    <div
      className="qty-cell-wrap"
      title={row.norm_reference || undefined}
    >
      <div className="qty-cell-top">
        <span className="cell-number">{qty != null ? fmt(qty) : '—'}</span>
        {showRestoreBtn && (
          <button
            className="qty-restore-btn"
            title={`Вернуть ручной объём: ${row.qty_manual_backup} ${row.unit}`}
            onMouseDown={(e) => e.preventDefault()}
            onClick={(e) => {
              e.stopPropagation();
              onQtyRestore(row.id);
            }}
          >↩</button>
        )}
      </div>
      {comment && <div className="qty-cell-comment">{comment}</div>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Column definitions
// ---------------------------------------------------------------------------

const DRAG_COL: Column<EstimateRow> = {
  key: '__drag',
  name: '',
  width: 32,
  frozen: true,
  renderCell: DragHandleCell,
};

const BASE_COLUMNS: Column<EstimateRow>[] = [
  { key: 'num', name: '№', width: 50, frozen: true, renderCell: NumericCell },
  { key: 'type', name: 'Тип', width: 52, renderCell: TypeCell },
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
    width: 120,
    renderEditCell: NumberEditor,
    renderCell: QtyCell,
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
const RECALC_BANNER_KEY = 'smeta_recalc_banner_seen';
const FLASH_DURATION_MS = 1800;

type SaveStatus = 'idle' | 'saving' | 'saved';

// ---------------------------------------------------------------------------
// EstimateGrid
// ---------------------------------------------------------------------------

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
  const [filterText, setFilterText] = useState('');

  // Flash animation state
  const [flashingIds, setFlashingIds] = useState<Set<string>>(new Set());
  const flashTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Toast state
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const toastIdRef = useRef(0);

  // One-time recalc banner
  const [bannerVisible, setBannerVisible] = useState(() => {
    try { return !localStorage.getItem(RECALC_BANNER_KEY); } catch { return false; }
  });

  // Ref для актуального rows (QtyCell читает через контекст)
  const rowsRef = useRef<EstimateRow[]>(rows);
  rowsRef.current = rows;

  // Ref для отображаемых строк (MoveCell использует для порядка при фильтрации)
  const displayedRowsRef = useRef<EstimateRow[]>([]);

  // Флаг: изменение произошло через handleRowsChange (не undo/redo)
  const didJustHandleChange = useRef(false);
  // Предыдущее значение rows для undo/redo flash
  const prevRowsRef = useRef<EstimateRow[] | null>(null);

  // ---------------------------------------------------------------------------
  // Utilities
  // ---------------------------------------------------------------------------

  const triggerSave = useCallback(() => {
    setSaveStatus('saving');
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      await onSave();
      setSaveStatus('saved');
      setTimeout(() => setSaveStatus('idle'), 2000);
    }, SAVE_DEBOUNCE_MS);
  }, [onSave]);

  const showToast = useCallback(
    (message: string, action?: { label: string; onClick: () => void }) => {
      const id = ++toastIdRef.current;
      setToasts((prev) => [...prev, { id, message, action }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 6000);
    },
    [],
  );

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const triggerFlash = useCallback((ids: Set<string>) => {
    if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    setFlashingIds(ids);
    flashTimerRef.current = setTimeout(() => setFlashingIds(new Set()), FLASH_DURATION_MS);
  }, []);

  // Stable restore callback для кнопки ↩ в ячейке
  const handleQtyRestore = useCallback(
    (rowId: string) => {
      const currentRows = rowsRef.current;
      const target = currentRows.find((r) => r.id === rowId);
      if (!target || target.qty_manual_backup == null) return;
      const restored = currentRows.map((r) =>
        r.id === rowId
          ? { ...r, qty: r.qty_manual_backup!, qty_overridden: true, qty_manual_backup: null }
          : r,
      );
      onRowsChange(restored);
      triggerSave();
    },
    [onRowsChange, triggerSave],
  );

  // ---------------------------------------------------------------------------
  // Drag-and-drop state
  // ---------------------------------------------------------------------------

  const [draggingId, setDraggingId] = useState<string | null>(null);
  const draggingIdRef = useRef<string | null>(null);
  const [dropTarget, setDropTarget] = useState<{ id: string; above: boolean } | null>(null);
  const dropTargetRef = useRef<{ id: string; above: boolean } | null>(null);

  const handleDragRowStart = useCallback((rowId: string, e: React.DragEvent) => {
    e.dataTransfer.effectAllowed = 'move';
    // Прозрачный ghost-образ — используем собственную визуализацию
    const ghost = document.createElement('div');
    ghost.style.position = 'absolute';
    ghost.style.top = '-9999px';
    document.body.appendChild(ghost);
    e.dataTransfer.setDragImage(ghost, 0, 0);
    setTimeout(() => document.body.removeChild(ghost), 0);

    setDraggingId(rowId);
    draggingIdRef.current = rowId;
  }, []);

  const handleDragRowEnd = useCallback(() => {
    setDraggingId(null);
    draggingIdRef.current = null;
    dropTargetRef.current = null;
    setDropTarget(null);
  }, []);

  const handleContainerDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    if (!draggingIdRef.current) return;
    e.dataTransfer.dropEffect = 'move';

    const el = document.elementFromPoint(e.clientX, e.clientY);
    const rowEl = el?.closest('[role="row"]') as HTMLElement | null;
    if (!rowEl) return;

    const ariaRowIndex = parseInt(rowEl.getAttribute('aria-rowindex') || '0');
    if (ariaRowIndex < 2) return; // заголовок таблицы

    const displayIdx = ariaRowIndex - 2;
    const displayed = displayedRowsRef.current;
    const targetRow = displayed[displayIdx];
    if (!targetRow || targetRow.id === draggingIdRef.current) return;

    const rect = rowEl.getBoundingClientRect();
    const above = e.clientY < rect.top + rect.height / 2;
    setDropTarget((prev) => {
      const next = prev?.id === targetRow.id && prev?.above === above ? prev : { id: targetRow.id, above };
      dropTargetRef.current = next;
      return next;
    });
  }, []);

  const handleContainerDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const sourceId = draggingIdRef.current;
    const target = dropTargetRef.current;
    if (!sourceId || !target) {
      setDraggingId(null);
      draggingIdRef.current = null;
      dropTargetRef.current = null;
      setDropTarget(null);
      return;
    }

    const currentRows = rowsRef.current;
    const fromIdx = currentRows.findIndex((r) => r.id === sourceId);
    if (fromIdx === -1) return;

    const reordered = [...currentRows];
    const [removed] = reordered.splice(fromIdx, 1);
    const newTargetIdx = reordered.findIndex((r) => r.id === target.id);
    if (newTargetIdx === -1) return;

    reordered.splice(target.above ? newTargetIdx : newTargetIdx + 1, 0, removed);
    onRowsChange(reordered);
    triggerSave();

    setDraggingId(null);
    draggingIdRef.current = null;
    dropTargetRef.current = null;
    setDropTarget(null);
  }, [onRowsChange, triggerSave]);

  const handleTypeChange = useCallback(
    (rowId: string, newType: EstimateRow['type']) => {
      const currentRows = rowsRef.current;
      const updated = currentRows.map((r) => {
        if (r.id !== rowId) return r;
        const next: EstimateRow = { ...r, type: newType };
        if (newType !== 'material') next.work_row_id = null;
        next.cost = calcCost(next);
        return next;
      });
      onRowsChange(updated);
      triggerSave();
    },
    [onRowsChange, triggerSave],
  );

  const dismissBanner = useCallback(() => {
    try { localStorage.setItem(RECALC_BANNER_KEY, '1'); } catch { /* ignore */ }
    setBannerVisible(false);
  }, []);

  // ---------------------------------------------------------------------------
  // Context value (стабильный — handleQtyRestore не меняется)
  // ---------------------------------------------------------------------------

  const gridContextValue = useMemo(
    () => ({
      rowsRef,
      displayedRowsRef,
      isReadonly,
      onQtyRestore: handleQtyRestore,
      onTypeChange: handleTypeChange,
      onDragRowStart: handleDragRowStart,
      onDragRowEnd: handleDragRowEnd,
    }),
    [isReadonly, handleQtyRestore, handleTypeChange, handleDragRowStart, handleDragRowEnd],
  );

  // ---------------------------------------------------------------------------
  // Effect: flash при undo/redo (внешнее изменение rows)
  // ---------------------------------------------------------------------------

  useEffect(() => {
    const prev = prevRowsRef.current;
    prevRowsRef.current = rows;

    if (prev === null) return; // первичная загрузка
    if (didJustHandleChange.current) {
      didJustHandleChange.current = false;
      return; // изменение пришло из handleRowsChange — не дублируем flash
    }

    // Undo/redo: выявляем материалы, у которых qty изменилось
    const prevMap = new Map(prev.map((r) => [r.id, r]));
    const changedQtyIds = new Set<string>();
    for (const r of rows) {
      const p = prevMap.get(r.id);
      if (p && p.qty !== r.qty && r.type === 'material') {
        changedQtyIds.add(r.id);
      }
    }
    // Порог: не флэшим если изменилась половина всех строк (скорее всего смена версии)
    if (changedQtyIds.size > 0 && changedQtyIds.size < rows.length * 0.5) {
      triggerFlash(changedQtyIds);
    }
  }, [rows, triggerFlash]);

  // ---------------------------------------------------------------------------
  // Cleanup
  // ---------------------------------------------------------------------------

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
      if (flashTimerRef.current) clearTimeout(flashTimerRef.current);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Rows change handler
  // ---------------------------------------------------------------------------

  const handleRowsChange = useCallback(
    (newDisplayed: EstimateRow[], { indexes }: RowsChangeData<EstimateRow>) => {
      const changedIds = new Set(indexes.map((i) => newDisplayed[i].id));
      const changedMap = new Map(
        newDisplayed.filter((r) => changedIds.has(r.id)).map((r) => [r.id, r]),
      );
      let merged: EstimateRow[] = rows.map((r) => {
        const updated = changedMap.get(r.id);
        if (!updated) return r;
        return { ...updated, cost: calcCost(updated) };
      });

      const newFlashIds = new Set<string>();

      for (const idx of indexes) {
        const changed = newDisplayed[idx];
        const original = rows.find((r) => r.id === changed.id);
        if (!original) continue;

        // --- Работа: изменился qty → пересчитать материалы ---
        if (changed.type === 'work' && changed.qty !== original.qty) {
          const result = applyWorkQuantityChange(merged, changed.id, changed.qty);
          merged = result.rows;
          result.recalcedIds.forEach((id) => newFlashIds.add(id));

          if (result.overriddenIds.length > 0) {
            const overriddenIds = result.overriddenIds;
            showToast(
              'Объём был задан вручную, сейчас пересчитан по нормативу.',
              {
                label: '↩ Вернуть',
                onClick: () => {
                  const currentRows = rowsRef.current;
                  const restored = currentRows.map((r) => {
                    if (!overriddenIds.includes(r.id) || r.qty_manual_backup == null) return r;
                    return { ...r, qty: r.qty_manual_backup, qty_overridden: true, qty_manual_backup: null };
                  });
                  onRowsChange(restored);
                  triggerSave();
                },
              },
            );
          }
        }

        // --- Материал: qty_overridden только что стал true → тост «задано вручную» ---
        if (
          changed.type === 'material' &&
          changed.qty_overridden &&
          !original.qty_overridden &&
          changed.qty_per_work_unit != null
        ) {
          const workRow = rows.find((r) => r.id === changed.work_row_id);
          const autoQty =
            workRow != null ? (workRow.qty ?? 0) * changed.qty_per_work_unit! : null;
          const rowId = changed.id;

          showToast(
            'Объём задан вручную, авто-расчёт отключён.',
            autoQty != null
              ? {
                  label: '↩ Вернуть авто',
                  onClick: () => {
                    const currentRows = rowsRef.current;
                    const restored = currentRows.map((r) =>
                      r.id === rowId ? { ...r, qty: autoQty, qty_overridden: false } : r,
                    );
                    onRowsChange(restored);
                    triggerSave();
                  },
                }
              : undefined,
          );
        }
      }

      if (newFlashIds.size > 0) {
        triggerFlash(newFlashIds);
      }

      didJustHandleChange.current = true;
      onRowsChange(merged);
      triggerSave();
    },
    [rows, onRowsChange, triggerSave, showToast, triggerFlash],
  );

  // ---------------------------------------------------------------------------
  // Displayed rows
  // ---------------------------------------------------------------------------

  const displayedRows = useMemo(() => {
    let filtered = rows;
    if (showOnlyAdded) filtered = filtered.filter((r) => r.optimization_note != null);
    if (activeTab === 'works') filtered = filtered.filter((r) => r.type === 'work');
    else if (activeTab === 'materials') filtered = filtered.filter((r) => r.type === 'material');

    if (filterText.trim()) {
      const needle = filterText.trim().toLowerCase();
      // When tabs filter to a single type, no section rows remain — simple filter
      if (activeTab !== 'all') {
        return filtered.filter((r) => (r.name ?? '').toLowerCase().includes(needle));
      }
      // In 'all' mode: include a section header only if ≥1 child row matches
      const matchingIds = new Set(
        filtered
          .filter((r) => r.type !== 'section' && (r.name ?? '').toLowerCase().includes(needle))
          .map((r) => r.id),
      );
      const neededSections = new Set<string>();
      let currentSection: string | null = null;
      for (const r of filtered) {
        if (r.type === 'section') {
          currentSection = r.id;
        } else if (matchingIds.has(r.id) && currentSection) {
          neededSections.add(currentSection);
        }
      }
      return filtered.filter(
        (r) => r.type === 'section' ? neededSections.has(r.id) : matchingIds.has(r.id),
      );
    }

    return filtered;
  }, [rows, activeTab, showOnlyAdded, filterText]);

  // Keep displayedRowsRef in sync for move operations
  displayedRowsRef.current = displayedRows;

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

  // ---------------------------------------------------------------------------
  // Columns
  // ---------------------------------------------------------------------------

  const columns = useMemo(() => {
    const base =
      activeTab === 'works'
        ? WORKS_COLUMNS
        : activeTab === 'materials'
          ? MATERIALS_COLUMNS
          : ALL_COLUMNS;

    if (isReadonly) {
      return base.map((c) => ({ ...c, editable: false, renderEditCell: undefined }));
    }
    // Insert DRAG_COL after SelectColumn (index 0)
    return [base[0], DRAG_COL, ...base.slice(1)];
  }, [activeTab, isReadonly]);

  // ---------------------------------------------------------------------------
  // Row class
  // ---------------------------------------------------------------------------

  const rowClass = useCallback(
    (row: EstimateRow) => {
      const classes: string[] = [];
      if (row.is_excluded) classes.push('row-excluded');
      if (row.optimization_confidence) classes.push(`row-proposal-${row.optimization_confidence}`);
      if (
        row.type !== 'section' &&
        row.optimization_note != null &&
        (row.price_work == null || row.price_material == null)
      )
        classes.push('row-unfilled');
      if (row.type === 'material' && row.qty_overridden && row.qty_per_work_unit != null)
        classes.push('row-qty-overridden');
      if (flashingIds.has(row.id)) classes.push('row-recalc-flash');
      if (draggingId === row.id) classes.push('row-dragging');
      if (dropTarget?.id === row.id) classes.push(dropTarget.above ? 'row-drop-above' : 'row-drop-below');
      return classes.join(' ') || undefined;
    },
    [flashingIds, draggingId, dropTarget],
  );

  // ---------------------------------------------------------------------------
  // Row renderer (section headers)
  // ---------------------------------------------------------------------------

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

  // ---------------------------------------------------------------------------
  // Legend
  // ---------------------------------------------------------------------------

  const hasExcluded = useMemo(() => rows.some((r) => r.is_excluded), [rows]);
  const hasProposalHigh = useMemo(() => rows.some((r) => r.optimization_confidence === 'high'), [rows]);
  const hasProposalMedium = useMemo(() => rows.some((r) => r.optimization_confidence === 'medium'), [rows]);
  const hasProposalLow = useMemo(() => rows.some((r) => r.optimization_confidence === 'low'), [rows]);
  const hasUnfilled = useMemo(
    () => rows.some((r) => r.type !== 'section' && r.optimization_note != null && (r.price_work == null || r.price_material == null)),
    [rows],
  );
  const hasOverridden = useMemo(
    () => rows.some((r) => r.type === 'material' && r.qty_overridden && r.qty_per_work_unit != null),
    [rows],
  );
  const hasNorms = useMemo(() => rows.some((r) => r.qty_per_work_unit != null), [rows]);

  const legendItems = useMemo(() => {
    const items: { color: string; border?: string; label: string; strikethrough?: boolean }[] = [
      { color: '#dbeafe', border: '#93c5fd', label: 'Раздел' },
    ];
    if (hasUnfilled) items.push({ color: '#fffbeb', border: '#fde68a', label: 'Нет цены' });
    if (hasExcluded) items.push({ color: '#fef2f2', border: '#fecaca', label: 'Исключена', strikethrough: true });
    if (hasProposalHigh) items.push({ color: '#f0fdf4', border: '#22c55e', label: 'Высокая уверенность' });
    if (hasProposalMedium) items.push({ color: '#fefce8', border: '#eab308', label: 'Средняя уверенность' });
    if (hasProposalLow) items.push({ color: '#fff7ed', border: '#f97316', label: 'Низкая уверенность' });
    if (hasOverridden) items.push({ color: '#fef3c7', border: '#f59e0b', label: 'Объём задан вручную' });
    return items;
  }, [hasExcluded, hasProposalHigh, hasProposalMedium, hasProposalLow, hasUnfilled, hasOverridden]);

  // ---------------------------------------------------------------------------
  // Misc
  // ---------------------------------------------------------------------------

  const handleUnfilledClick = useCallback(() => {
    setShowOnlyAdded(true);
  }, []);

  const rowKeyGetter = useCallback((row: EstimateRow) => row.id, []);

  const saveStatusLabel =
    saveStatus === 'saving'
      ? 'Сохранение...'
      : saveStatus === 'saved'
        ? 'Сохранено'
        : '';

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <GridContext.Provider value={gridContextValue}>
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
          <div style={{ fontSize: '13px', color: '#64748b', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
            <span>
              Строк: {displayedRows.length}
              {selectedRowIds.size > 0 && (
                <span style={{ marginLeft: 10, color: '#2563eb', fontWeight: 600 }}>
                  Выбрано: {selectedRowIds.size}
                </span>
              )}
            </span>
            <div className="estimate-grid-search">
              <span className="estimate-grid-search-icon">🔍</span>
              <input
                className="estimate-grid-search-input"
                type="text"
                placeholder="Поиск по наименованию..."
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
              />
              {filterText && (
                <button
                  className="estimate-grid-search-clear"
                  onClick={() => setFilterText('')}
                  title="Сбросить поиск"
                >✕</button>
              )}
            </div>
          </div>
          <div className="estimate-grid-actions">
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

        {/* Legend */}
        {legendItems.length > 0 && (
          <div className="estimate-grid-legend">
            <span className="estimate-grid-legend-title">Обозначения:</span>
            {legendItems.map((item) => (
              <span key={item.label} className="estimate-grid-legend-item">
                <span
                  className="estimate-grid-legend-swatch"
                  style={{
                    background: item.color,
                    borderColor: item.border ?? '#e2e8f0',
                  }}
                />
                <span style={{ textDecoration: item.strikethrough ? 'line-through' : undefined }}>
                  {item.label}
                </span>
              </span>
            ))}
          </div>
        )}

        {/* Однократный баннер об авто-расчёте */}
        {hasNorms && bannerVisible && (
          <div className="estimate-grid-recalc-banner">
            <span>
              В этой смете работает авто-расчёт материалов. При изменении объёма работы материалы пересчитаются автоматически.
            </span>
            <button className="estimate-grid-recalc-banner-dismiss" onClick={dismissBanner}>
              Понятно
            </button>
          </div>
        )}

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
        <div
          onDragOver={handleContainerDragOver}
          onDrop={handleContainerDrop}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) {
              dropTargetRef.current = null;
              setDropTarget(null);
            }
          }}
        >
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

        {/* Toasts */}
        {toasts.length > 0 && (
          <div className="estimate-grid-toasts">
            {toasts.map((t) => (
              <div key={t.id} className="estimate-grid-toast">
                <span>{t.message}</span>
                {t.action && (
                  <button
                    className="estimate-grid-toast-action"
                    onClick={() => { t.action!.onClick(); dismissToast(t.id); }}
                  >
                    {t.action.label}
                  </button>
                )}
                <button
                  className="estimate-grid-toast-dismiss"
                  onClick={() => dismissToast(t.id)}
                  title="Закрыть"
                >✕</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </GridContext.Provider>
  );
};

export default EstimateGrid;
