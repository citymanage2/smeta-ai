import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { GenericRow } from '../../types';
import './GenericGrid.css';

interface GenericGridProps {
  rows: GenericRow[];
  isDirty?: boolean;
  isSaving?: boolean;
  isReadonly?: boolean;
  onRowsChange: (rows: GenericRow[]) => void;
  onSave: () => Promise<void>;
}

type Tab = 'all' | 'works' | 'materials';

// Characters-to-pixels ratio for column width estimation
const CHAR_PX = 8;
const COL_MIN = 60;
const COL_MAX = 280;
const COL_MAX_NAME = 500;
const COL_MAX_PRICE = 90;
const COL_PAD = 24;
const UNDO_LIMIT = 50;

// Column keys that are auto-generated or need special handling
const EXCLUDED_COLS = new Set(['№', '#']);

// Type column key variants (case-insensitive match)
const TYPE_COL = 'Тип';
const NAME_COL = 'Наименование';

// Auto-recalc: пары «цена → стоимость», умножаются на кол-во
// Каждая пара: priceCol × qty = costCol
const QTY_KEYWORDS = ['кол-во', 'количество', 'кол.', 'объем', 'объём', 'кол'];
const PRICE_WORK_KEYWORDS = ['цена работ', 'цена работы'];
const PRICE_MAT_KEYWORDS = ['цена материал'];
const COST_WORK_KEYWORDS = ['стоимость работ'];
const COST_MAT_KEYWORDS = ['стоимость материал'];

function colMatches(col: string, keywords: string[]): boolean {
  const lower = col.trim().toLowerCase();
  return keywords.some((kw) => lower.startsWith(kw));
}

interface RecalcPair { priceCol: string; costCol: string }

interface RecalcConfig {
  qtyCol: string | null;
  pairs: RecalcPair[];
}

function findRecalcConfig(columns: string[]): RecalcConfig {
  let qtyCol: string | null = null;
  let priceWorkCol: string | null = null;
  let priceMatCol: string | null = null;
  let costWorkCol: string | null = null;
  let costMatCol: string | null = null;

  for (const col of columns) {
    if (!qtyCol && colMatches(col, QTY_KEYWORDS)) { qtyCol = col; continue; }
    if (!priceWorkCol && colMatches(col, PRICE_WORK_KEYWORDS)) { priceWorkCol = col; continue; }
    if (!priceMatCol && colMatches(col, PRICE_MAT_KEYWORDS)) { priceMatCol = col; continue; }
    if (!costWorkCol && colMatches(col, COST_WORK_KEYWORDS)) { costWorkCol = col; continue; }
    if (!costMatCol && colMatches(col, COST_MAT_KEYWORDS)) { costMatCol = col; continue; }
  }

  const pairs: RecalcPair[] = [];
  if (priceWorkCol && costWorkCol) pairs.push({ priceCol: priceWorkCol, costCol: costWorkCol });
  if (priceMatCol && costMatCol) pairs.push({ priceCol: priceMatCol, costCol: costMatCol });

  return { qtyCol, pairs };
}

function applyRecalc(
  cells: Record<string, string | number | null>,
  config: RecalcConfig,
): Record<string, string | number | null> {
  if (!config.qtyCol || config.pairs.length === 0) return cells;
  const qty = Number(cells[config.qtyCol] ?? 0);
  const result = { ...cells };
  for (const { priceCol, costCol } of config.pairs) {
    result[costCol] = Math.round(qty * Number(cells[priceCol] ?? 0));
  }
  return result;
}

const PRICE_COST_KEYWORDS = [
  ...PRICE_WORK_KEYWORDS,
  ...PRICE_MAT_KEYWORDS,
  ...COST_WORK_KEYWORDS,
  ...COST_MAT_KEYWORDS,
];

function estimateColWidth(header: string, rows: GenericRow[], maxWidth = COL_MAX): number {
  let max = header.length;
  for (const row of rows) {
    const val = row.cells[header];
    const len = val == null ? 0 : String(val).length;
    if (len > max) max = len;
  }
  return Math.min(maxWidth, Math.max(COL_MIN, max * CHAR_PX + COL_PAD));
}

function getTypeClass(typeVal: string | null): string {
  if (!typeVal) return '';
  const v = String(typeVal).trim();
  if (v === 'Работа') return 'gg-row-work';
  if (v === 'Материал') return 'gg-row-material';
  return '';
}

interface CellInputProps {
  value: string | number | null;
  readOnly: boolean;
  onChange: (val: string) => void;
  isTypeBadge?: boolean;
}

const CellInput: React.FC<CellInputProps> = ({ value, readOnly, onChange, isTypeBadge }) => {
  const [localVal, setLocalVal] = useState(String(value ?? ''));
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setLocalVal(String(value ?? ''));
  }, [value]);

  if (isTypeBadge) {
    const v = String(value ?? '').trim();
    const badgeClass = v === 'Работа' ? 'gg-badge-work' : v === 'Материал' ? 'gg-badge-material' : '';
    const displayLabel = v === 'Работа' ? 'Р' : v === 'Материал' ? 'М' : v;
    if (readOnly || !badgeClass) {
      return <span className={`gg-badge ${badgeClass}`} title={v || undefined}>{displayLabel || '—'}</span>;
    }
    return (
      <input
        ref={inputRef}
        className="gg-cell-input"
        value={localVal}
        title={v}
        onChange={(e) => setLocalVal(e.target.value)}
        onBlur={() => onChange(localVal)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') inputRef.current?.blur();
          if (e.key === 'Escape') { setLocalVal(String(value ?? '')); inputRef.current?.blur(); }
        }}
      />
    );
  }

  return (
    <input
      ref={inputRef}
      className="gg-cell-input"
      value={localVal}
      readOnly={readOnly}
      onChange={(e) => setLocalVal(e.target.value)}
      onBlur={() => onChange(localVal)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') inputRef.current?.blur();
        if (e.key === 'Escape') { setLocalVal(String(value ?? '')); inputRef.current?.blur(); }
      }}
    />
  );
};

const GenericGrid: React.FC<GenericGridProps> = ({
  rows,
  isDirty,
  isSaving,
  isReadonly,
  onRowsChange,
  onSave,
}) => {
  const [activeTab, setActiveTab] = useState<Tab>('all');
  const [searchText, setSearchText] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [undoStack, setUndoStack] = useState<GenericRow[][]>([]);
  const [redoStack, setRedoStack] = useState<GenericRow[][]>([]);
  const searchRef = useRef<HTMLInputElement>(null);

  // Derive column list (no № / #)
  const allColumns = useMemo(
    () =>
      rows.length > 0
        ? Object.keys(rows[0].cells).filter((k) => !EXCLUDED_COLS.has(k))
        : [],
    [rows],
  );

  const hasTypeCol = allColumns.includes(TYPE_COL);
  const hasNameCol = allColumns.includes(NAME_COL);
  const isEnhanced = hasTypeCol;

  const recalcConfig = useMemo(() => findRecalcConfig(allColumns), [allColumns]);

  // Reorder columns: Тип first (if present), then Наименование, then rest
  const columns = useMemo(() => {
    if (!isEnhanced) return allColumns;
    const rest = allColumns.filter((c) => c !== TYPE_COL && c !== NAME_COL);
    const ordered: string[] = [];
    if (hasTypeCol) ordered.push(TYPE_COL);
    if (hasNameCol) ordered.push(NAME_COL);
    return [...ordered, ...rest];
  }, [allColumns, isEnhanced, hasTypeCol, hasNameCol]);

  const colWidths = useMemo(
    () =>
      Object.fromEntries(
        columns.map((col) => {
          const isName = col === NAME_COL;
          const isPriceCost = PRICE_COST_KEYWORDS.some((kw) =>
            col.trim().toLowerCase().startsWith(kw),
          );
          const maxWidth = isName ? COL_MAX_NAME : isPriceCost ? COL_MAX_PRICE : COL_MAX;
          return [col, estimateColWidth(col, rows, maxWidth)];
        }),
      ),
    [columns, rows],
  );

  // Tab filtering
  const tabFiltered = useMemo(() => {
    if (!isEnhanced || activeTab === 'all') return rows;
    const target = activeTab === 'works' ? 'Работа' : 'Материал';
    return rows.filter((r) => String(r.cells[TYPE_COL] ?? '').trim() === target);
  }, [rows, activeTab, isEnhanced]);

  // Search filtering
  const displayedRows = useMemo(() => {
    if (!searchText.trim()) return tabFiltered;
    const q = searchText.toLowerCase();
    return tabFiltered.filter((r) => {
      if (hasNameCol) {
        return String(r.cells[NAME_COL] ?? '').toLowerCase().includes(q);
      }
      // Fallback: search all text values
      return Object.values(r.cells).some(
        (v) => v != null && String(v).toLowerCase().includes(q),
      );
    });
  }, [tabFiltered, searchText, hasNameCol]);

  // Row counts for tabs
  const workCount = useMemo(
    () => (isEnhanced ? rows.filter((r) => String(r.cells[TYPE_COL] ?? '').trim() === 'Работа').length : 0),
    [rows, isEnhanced],
  );
  const materialCount = useMemo(
    () => (isEnhanced ? rows.filter((r) => String(r.cells[TYPE_COL] ?? '').trim() === 'Материал').length : 0),
    [rows, isEnhanced],
  );

  // Totals (only in enhanced mode where cost columns exist)
  const computedTotals = useMemo(() => {
    if (!isEnhanced) return null;
    const costWorkCol = allColumns.find((c) => colMatches(c, COST_WORK_KEYWORDS)) ?? null;
    const costMatCol = allColumns.find((c) => colMatches(c, COST_MAT_KEYWORDS)) ?? null;
    if (!costWorkCol && !costMatCol) return null;
    let sumWork = 0;
    let sumMat = 0;
    for (const r of rows) {
      const type = String(r.cells[TYPE_COL] ?? '').trim();
      if (costWorkCol && type === 'Работа') sumWork += Number(r.cells[costWorkCol] ?? 0);
      if (costMatCol && type === 'Материал') sumMat += Number(r.cells[costMatCol] ?? 0);
    }
    const overhead = sumWork * 0.03;
    const transport = sumMat * 0.03;
    return { sumWork, overhead, sumMat, transport, grand: sumWork + overhead + sumMat + transport };
  }, [rows, isEnhanced, allColumns]);

  const fmtRub = (n: number) => Math.round(n).toLocaleString('ru-RU');

  // Cell change handler — records undo history
  const handleCellChange = useCallback(
    (rowId: string, colKey: string, rawVal: string) => {
      const numericCandidate = rawVal.trim().replace(',', '.');
      const parsed =
        numericCandidate !== '' && !isNaN(Number(numericCandidate))
          ? Number(numericCandidate)
          : rawVal || null;

      setUndoStack((prev) => [...prev.slice(-UNDO_LIMIT), rows]);
      setRedoStack([]);

      const { qtyCol, pairs } = recalcConfig;
      const priceColsSet = new Set(pairs.map((p) => p.priceCol));
      const costColsSet = new Set(pairs.map((p) => p.costCol));
      const shouldRecalc =
        pairs.length > 0 &&
        qtyCol != null &&
        !costColsSet.has(colKey) &&
        (colKey === qtyCol || priceColsSet.has(colKey));

      const updated = rows.map((r) => {
        if (r.row_id !== rowId) return r;
        const newCells = { ...r.cells, [colKey]: parsed };
        return { ...r, cells: shouldRecalc ? applyRecalc(newCells, recalcConfig) : newCells };
      });
      onRowsChange(updated);
    },
    [rows, onRowsChange, recalcConfig],
  );

  // Undo
  const handleUndo = useCallback(() => {
    if (undoStack.length === 0) return;
    const prev = undoStack[undoStack.length - 1];
    setRedoStack((r) => [...r, rows]);
    setUndoStack((u) => u.slice(0, -1));
    onRowsChange(prev);
  }, [undoStack, rows, onRowsChange]);

  // Redo
  const handleRedo = useCallback(() => {
    if (redoStack.length === 0) return;
    const next = redoStack[redoStack.length - 1];
    setUndoStack((u) => [...u, rows]);
    setRedoStack((r) => r.slice(0, -1));
    onRowsChange(next);
  }, [redoStack, rows, onRowsChange]);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isReadonly) return;
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key === 'z' && !e.shiftKey) { e.preventDefault(); handleUndo(); }
      if (mod && (e.key === 'y' || (e.key === 'z' && e.shiftKey))) { e.preventDefault(); handleRedo(); }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [handleUndo, handleRedo, isReadonly]);

  // Checkbox helpers
  const allChecked =
    displayedRows.length > 0 && displayedRows.every((r) => selectedIds.has(r.row_id));
  const someChecked = displayedRows.some((r) => selectedIds.has(r.row_id));

  const toggleAll = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (allChecked) {
        displayedRows.forEach((r) => next.delete(r.row_id));
      } else {
        displayedRows.forEach((r) => next.add(r.row_id));
      }
      return next;
    });
  };

  const toggleRow = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  if (rows.length === 0) {
    return <div className="gg-empty">Нет данных для отображения</div>;
  }

  const saveDisabled = !isDirty || isSaving || isReadonly;

  return (
    <div className="gg-wrap">
      {/* ── Tabs (enhanced mode only) ────────────────────────────────────── */}
      {isEnhanced && (
        <div className="gg-tabs">
          <button
            className={`gg-tab ${activeTab === 'all' ? 'active' : ''}`}
            onClick={() => setActiveTab('all')}
          >
            Полный перечень
          </button>
          <button
            className={`gg-tab ${activeTab === 'works' ? 'active' : ''}`}
            onClick={() => setActiveTab('works')}
          >
            Работы
            {workCount > 0 && <span className="gg-tab-count">{workCount}</span>}
          </button>
          <button
            className={`gg-tab ${activeTab === 'materials' ? 'active' : ''}`}
            onClick={() => setActiveTab('materials')}
          >
            Материалы
            {materialCount > 0 && <span className="gg-tab-count">{materialCount}</span>}
          </button>
        </div>
      )}

      {/* ── Toolbar ──────────────────────────────────────────────────────── */}
      <div className="gg-toolbar">
        {/* Row count */}
        <span className="gg-row-count">Строк: {displayedRows.length}</span>

        {/* Search */}
        {(hasNameCol || !isEnhanced) && (
          <div className="gg-search-wrap">
            <svg className="gg-search-icon" viewBox="0 0 16 16" fill="none">
              <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.5" />
              <path d="M10.5 10.5L14 14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input
              ref={searchRef}
              className="gg-search-input"
              placeholder="Поиск по наименованию..."
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
            />
            {searchText && (
              <button className="gg-search-clear" onClick={() => setSearchText('')}>✕</button>
            )}
          </div>
        )}

        {/* Right side controls */}
        <div className="gg-toolbar-right">
          {/* Selection info */}
          {selectedIds.size > 0 && (
            <span className="gg-selection-count">Выбрано: {selectedIds.size}</span>
          )}

          {/* Undo / Redo */}
          {!isReadonly && (
            <div className="gg-history-btns">
              <button
                className="gg-history-btn"
                onClick={handleUndo}
                disabled={undoStack.length === 0}
                title="Отменить (Ctrl+Z)"
              >
                ↩
              </button>
              <button
                className="gg-history-btn"
                onClick={handleRedo}
                disabled={redoStack.length === 0}
                title="Повторить (Ctrl+Y)"
              >
                ↪
              </button>
            </div>
          )}

          {/* Save */}
          <button className="gg-save-btn" onClick={onSave} disabled={saveDisabled}>
            {isSaving ? 'Сохранение...' : 'Сохранить'}
          </button>
        </div>
      </div>

      {/* ── Totals block ─────────────────────────────────────────────────── */}
      {computedTotals && (
        <div className="gg-totals">
          <div className="gg-totals-title">Итоги по смете</div>
          <div className="gg-totals-rows">
            {[
              { label: 'Сумма по работам:', value: computedTotals.sumWork },
              { label: 'Накладные расходы 3%:', value: computedTotals.overhead },
              { label: 'Сумма по материалам:', value: computedTotals.sumMat },
              { label: 'Транспортные расходы 3%:', value: computedTotals.transport },
            ].map(({ label, value }) => (
              <div key={label} className="gg-totals-row">
                <span>{label}</span>
                <span className="gg-totals-val">{fmtRub(value)} ₽</span>
              </div>
            ))}
          </div>
          <div className="gg-totals-grand">
            <span>ИТОГО ПО СМЕТЕ:</span>
            <span className="gg-totals-grand-val">{fmtRub(computedTotals.grand)} ₽</span>
          </div>
        </div>
      )}

      {/* ── Table ────────────────────────────────────────────────────────── */}
      <div className="gg-scroll">
        <table className="gg-table">
          <thead>
            <tr>
              {/* Checkbox */}
              <th className="gg-th gg-th-check">
                <input
                  type="checkbox"
                  className="gg-checkbox"
                  checked={allChecked}
                  ref={(el) => { if (el) el.indeterminate = someChecked && !allChecked; }}
                  onChange={toggleAll}
                />
              </th>
              {/* Row number */}
              <th className="gg-th gg-th-num">№</th>
              {/* Data columns */}
              {columns.map((col) => (
                <th
                  key={col}
                  className="gg-th"
                  style={{ width: colWidths[col], minWidth: colWidths[col] }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayedRows.map((row, idx) => {
              const typeVal = hasTypeCol ? String(row.cells[TYPE_COL] ?? '').trim() : '';
              const rowClass = `gg-tr ${getTypeClass(typeVal)} ${selectedIds.has(row.row_id) ? 'gg-tr-selected' : ''}`;

              return (
                <tr key={row.row_id} className={rowClass}>
                  {/* Checkbox */}
                  <td className="gg-td gg-td-check">
                    <input
                      type="checkbox"
                      className="gg-checkbox"
                      checked={selectedIds.has(row.row_id)}
                      onChange={() => toggleRow(row.row_id)}
                    />
                  </td>
                  {/* Row number */}
                  <td className="gg-td gg-td-num">{idx + 1}</td>
                  {/* Data cells */}
                  {columns.map((col) => (
                    <td
                      key={col}
                      className={`gg-td${col === NAME_COL ? ' gg-td-name' : ''}`}
                      title={col === NAME_COL ? (String(row.cells[col] ?? '')) || undefined : undefined}
                    >
                      <CellInput
                        value={row.cells[col]}
                        readOnly={!!isReadonly}
                        isTypeBadge={isEnhanced && col === TYPE_COL}
                        onChange={(val) => handleCellChange(row.row_id, col, val)}
                      />
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>

        {displayedRows.length === 0 && searchText && (
          <div className="gg-no-results">
            Ничего не найдено по запросу «{searchText}»
          </div>
        )}
      </div>
    </div>
  );
};

export default GenericGrid;
