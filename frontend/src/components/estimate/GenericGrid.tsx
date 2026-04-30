import React, { useCallback, useEffect, useRef, useState } from 'react';
import { GenericRow } from '../../types';

interface GenericGridProps {
  rows: GenericRow[];
  isDirty?: boolean;
  isSaving?: boolean;
  isReadonly?: boolean;
  onRowsChange: (rows: GenericRow[]) => void;
  onSave: () => Promise<void>;
}

const thStyle: React.CSSProperties = {
  padding: '8px 10px',
  textAlign: 'left',
  fontSize: '12px',
  fontWeight: 600,
  color: '#475569',
  background: '#f8fafc',
  borderBottom: '1px solid #e2e8f0',
  whiteSpace: 'nowrap',
  userSelect: 'none',
};

const tdStyle: React.CSSProperties = {
  padding: '0',
  borderBottom: '1px solid #f1f5f9',
  verticalAlign: 'middle',
};

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
      style={{
        width: '100%',
        border: 'none',
        background: 'transparent',
        fontSize: '13px',
        padding: '6px 10px',
        outline: 'none',
        cursor: readOnly ? 'default' : 'text',
        color: '#1e293b',
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
  const columns = rows.length > 0 ? Object.keys(rows[0].cells) : [];

  const handleCellChange = useCallback(
    (rowId: string, colKey: string, rawVal: string) => {
      const numericCandidate = rawVal.trim().replace(',', '.');
      const parsed = numericCandidate !== '' && !isNaN(Number(numericCandidate))
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
    return (
      <div
        style={{
          padding: '32px',
          textAlign: 'center',
          color: '#94a3b8',
          background: '#fff',
          border: '1px solid #e2e8f0',
          borderRadius: '10px',
          fontSize: '14px',
        }}
      >
        Нет данных для отображения
      </div>
    );
  }

  const saveDisabled = !isDirty || isSaving || isReadonly;

  return (
    <div
      style={{
        background: '#fff',
        border: '1px solid #e2e8f0',
        borderRadius: '10px',
        overflow: 'hidden',
      }}
    >
      {/* Toolbar */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid #e2e8f0',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          background: '#fff',
        }}
      >
        <button
          onClick={onSave}
          disabled={saveDisabled}
          style={{
            padding: '6px 18px',
            borderRadius: '6px',
            fontSize: '13px',
            fontWeight: 600,
            border: 'none',
            background: saveDisabled ? '#e2e8f0' : '#2563eb',
            color: saveDisabled ? '#94a3b8' : '#fff',
            cursor: saveDisabled ? 'not-allowed' : 'pointer',
            transition: 'background 0.15s',
          }}
        >
          {isSaving ? 'Сохранение...' : 'Сохранить'}
        </button>

        {isDirty && !isSaving && (
          <span style={{ color: '#f59e0b', fontSize: '12px', fontWeight: 500 }}>
            Несохранённые изменения
          </span>
        )}

        <span style={{ marginLeft: 'auto', color: '#94a3b8', fontSize: '12px' }}>
          {rows.length} строк · {columns.length} колонок
        </span>
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto', maxHeight: '65vh', overflowY: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '13px' }}>
          <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
            <tr>
              <th style={{ ...thStyle, width: 44, textAlign: 'center', padding: '8px 6px' }}>
                №
              </th>
              {columns.map((col) => (
                <th key={col} style={thStyle}>
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr
                key={row.row_id}
                style={{
                  background: idx % 2 === 0 ? '#fff' : '#fafafa',
                }}
              >
                <td
                  style={{
                    ...tdStyle,
                    color: '#94a3b8',
                    textAlign: 'center',
                    fontSize: '11px',
                    padding: '6px',
                  }}
                >
                  {idx + 1}
                </td>
                {columns.map((col) => (
                  <td key={col} style={tdStyle}>
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
