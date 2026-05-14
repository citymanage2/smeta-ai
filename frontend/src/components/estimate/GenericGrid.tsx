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

// Characters-to-pixels ratio for column width estimation
const CHAR_PX = 8;
const COL_MIN = 60;
const COL_MAX = 220;
const COL_PAD = 24;

function estimateColWidth(header: string, rows: GenericRow[]): number {
  let max = header.length;
  for (const row of rows) {
    const val = row.cells[header];
    const len = val == null ? 0 : String(val).length;
    if (len > max) max = len;
  }
  return Math.min(COL_MAX, Math.max(COL_MIN, max * CHAR_PX + COL_PAD));
}

interface CellInputProps {
  value: string | number | null;
  readOnly: boolean;
  onChange: (val: string) => void;
}

const CellInput: React.FC<CellInputProps> = ({ value, readOnly, onChange }) => {
  const [localVal, setLocalVal] = useState(String(value ?? ''));
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    setLocalVal(String(value ?? ''));
  }, [value]);

  return (
    <input
      ref={inputRef}
      className="generic-grid-cell-input"
      value={localVal}
      readOnly={readOnly}
      onChange={(e) => setLocalVal(e.target.value)}
      onBlur={() => onChange(localVal)}
      onKeyDown={(e) => {
        if (e.key === 'Enter') inputRef.current?.blur();
        if (e.key === 'Escape') {
          setLocalVal(String(value ?? ''));
          inputRef.current?.blur();
        }
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
  const columns = useMemo(
    () =>
      rows.length > 0
        ? Object.keys(rows[0].cells).filter((k) => k !== '№' && k !== '#')
        : [],
    [rows],
  );

  const colWidths = useMemo(
    () => Object.fromEntries(columns.map((col) => [col, estimateColWidth(col, rows)])),
    [columns, rows],
  );

  const handleCellChange = useCallback(
    (rowId: string, colKey: string, rawVal: string) => {
      const numericCandidate = rawVal.trim().replace(',', '.');
      const parsed =
        numericCandidate !== '' && !isNaN(Number(numericCandidate))
          ? Number(numericCandidate)
          : rawVal || null;
      const updated = rows.map((r) =>
        r.row_id === rowId ? { ...r, cells: { ...r.cells, [colKey]: parsed } } : r,
      );
      onRowsChange(updated);
    },
    [rows, onRowsChange],
  );

  if (rows.length === 0) {
    return <div className="generic-grid-empty">Нет данных для отображения</div>;
  }

  const saveDisabled = !isDirty || isSaving || isReadonly;

  return (
    <div className="generic-grid-wrap">
      {/* Toolbar */}
      <div className="generic-grid-toolbar">
        <button
          className="generic-grid-save-btn"
          onClick={onSave}
          disabled={saveDisabled}
        >
          {isSaving ? 'Сохранение...' : 'Сохранить'}
        </button>

        {isDirty && !isSaving && (
          <span className="generic-grid-dirty">Несохранённые изменения</span>
        )}

        <span className="generic-grid-meta">
          {rows.length} строк · {columns.length} колонок
        </span>
      </div>

      {/* Table */}
      <div className="generic-grid-scroll">
        <table className="generic-grid-table">
          <thead>
            <tr>
              <th className="generic-grid-th generic-grid-th-num">№</th>
              {columns.map((col) => (
                <th
                  key={col}
                  className="generic-grid-th"
                  style={{ width: colWidths[col], minWidth: colWidths[col] }}
                >
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr key={row.row_id} className="generic-grid-tr">
                <td className="generic-grid-td generic-grid-td-num">{idx + 1}</td>
                {columns.map((col) => (
                  <td key={col} className="generic-grid-td">
                    <CellInput
                      value={row.cells[col]}
                      readOnly={!!isReadonly}
                      onChange={(val) => handleCellChange(row.row_id, col, val)}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default GenericGrid;
