import React, { useState, useCallback } from 'react'
import { X, Download, ArrowRight, ArrowLeft, FileSpreadsheet } from 'lucide-react'
import { SectionTab } from '../../types/summary'
import { LumaSpin } from '../ui/LumaSpin'
import { customExport } from '../../api/summaryEstimate'

// ── Column definitions ──────────────────────────────────────────────────────

interface ColDef {
  key: string
  label: string
  width: number
  isNumber: boolean
}

const ALL_COLUMNS: ColDef[] = [
  { key: 'num',            label: '№',             width: 52,  isNumber: false },
  { key: 'name',           label: 'Наименование',  width: 320, isNumber: false },
  { key: 'unit',           label: 'Ед. изм.',      width: 80,  isNumber: false },
  { key: 'qty',            label: 'Кол-во',        width: 90,  isNumber: true  },
  { key: 'price_work',     label: 'Цена работ',    width: 120, isNumber: true  },
  { key: 'cost_work',      label: 'Стоим. работ',  width: 130, isNumber: true  },
  { key: 'price_material', label: 'Цена матер.',   width: 120, isNumber: true  },
  { key: 'cost_material',  label: 'Стоим. матер.', width: 130, isNumber: true  },
]

const DEFAULT_VISIBLE = ALL_COLUMNS.map(c => c.key)

// ── Row type options ─────────────────────────────────────────────────────────

type RowTypeOption = 'work' | 'material' | 'both'

// ── Internal row type ────────────────────────────────────────────────────────

interface ExportRow {
  _id: string
  section_name: string
  num: number | null
  name: string
  unit: string
  qty: number | null
  price_work: number | null
  cost_work: number | null
  price_material: number | null
  cost_material: number | null
}

function buildExportRows(
  sections: SectionTab[],
  selectedIds: string[],
  rowTypes: string[],
): ExportRow[] {
  const filtered =
    selectedIds.length > 0
      ? sections.filter(s => selectedIds.includes(s.card_id))
      : sections

  const result: ExportRow[] = []
  let num = 1

  for (const sec of filtered) {
    for (const row of sec.rows) {
      if (row.type === 'section') continue
      if (!rowTypes.includes(row.type)) continue
      if (row.is_excluded) continue

      const qty = row.qty ?? 0
      const pw = row.price_work ?? null
      const pm = row.price_material ?? null

      result.push({
        _id: row.id,
        section_name: sec.card_name,
        num: num++,
        name: row.name ?? '',
        unit: row.unit ?? '',
        qty: row.qty ?? null,
        price_work: pw,
        cost_work: pw != null ? Math.round(qty * pw * 100) / 100 : null,
        price_material: pm,
        cost_material: pm != null ? Math.round(qty * pm * 100) / 100 : null,
      })
    }
  }

  return result
}

function fmtNum(v: number | null): string {
  if (v == null) return ''
  return v.toLocaleString('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

// ── Props ────────────────────────────────────────────────────────────────────

interface Props {
  projectId: string
  projectName?: string
  sections: SectionTab[]
  onClose: () => void
}

// ── Component ────────────────────────────────────────────────────────────────

const CustomExportModal: React.FC<Props> = ({ projectId, projectName, sections, onClose }) => {
  // Step
  const [step, setStep] = useState<'config' | 'preview'>('config')

  // Config state
  const [selectedIds, setSelectedIds] = useState<string[]>([])   // empty = all
  const [rowTypeOpt, setRowTypeOpt] = useState<RowTypeOption>('both')
  const [visibleCols, setVisibleCols] = useState<string[]>(DEFAULT_VISIBLE)

  // Preview state
  const [rows, setRows] = useState<ExportRow[]>([])
  const [downloading, setDownloading] = useState(false)
  const [showSection, setShowSection] = useState(false)

  // ── Config handlers ────────────────────────────────────────────────────────

  const toggleSection = (id: string) => {
    setSelectedIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id],
    )
  }

  const toggleCol = (key: string) => {
    setVisibleCols(prev =>
      prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key],
    )
  }

  const resolvedRowTypes = (): string[] => {
    if (rowTypeOpt === 'work') return ['work']
    if (rowTypeOpt === 'material') return ['material']
    return ['work', 'material']
  }

  const handleNext = () => {
    const built = buildExportRows(sections, selectedIds, resolvedRowTypes())
    setRows(built)
    // Показываем колонку раздела, если выбрано больше одного раздела
    const effSections =
      selectedIds.length > 0
        ? sections.filter(s => selectedIds.includes(s.card_id))
        : sections
    setShowSection(effSections.length > 1)
    setStep('preview')
  }

  // ── Preview handlers ───────────────────────────────────────────────────────

  const updateCell = useCallback(
    (rowIdx: number, key: keyof ExportRow, raw: string) => {
      setRows(prev => {
        const next = [...prev]
        const r = { ...next[rowIdx] }
        if (key === 'name' || key === 'unit' || key === 'section_name') {
          ;(r as Record<string, unknown>)[key] = raw
        } else {
          const parsed = raw === '' ? null : parseFloat(raw.replace(',', '.'))
          ;(r as Record<string, unknown>)[key] = isNaN(parsed as number) ? null : parsed
        }
        next[rowIdx] = r
        return next
      })
    },
    [],
  )

  const deleteRow = (idx: number) => {
    setRows(prev => prev.filter((_, i) => i !== idx))
  }

  const handleDownload = async () => {
    setDownloading(true)
    try {
      const effCols = showSection ? ['section_name', ...visibleCols] : visibleCols
      // Маппим ключ section_name → section для бэкенда
      const beVisibleCols = effCols.map(k => (k === 'section_name' ? 'section' : k))

      await customExport(
        projectId,
        {
          selected_section_ids: selectedIds,
          row_types: resolvedRowTypes(),
          visible_columns: beVisibleCols,
          rows: rows.map(r => ({
            section_name: r.section_name,
            num: r.num,
            name: r.name,
            unit: r.unit,
            qty: r.qty,
            price_work: r.price_work,
            cost_work: r.cost_work,
            price_material: r.price_material,
            cost_material: r.cost_material,
          })),
        },
        `vygruzka_${projectName ?? projectId}.xlsx`,
      )
    } finally {
      setDownloading(false)
    }
  }

  // ── Effective column list for preview table ────────────────────────────────

  const previewCols: ColDef[] = [
    ...(showSection
      ? [{ key: 'section_name', label: 'Раздел', width: 160, isNumber: false }]
      : []),
    ...ALL_COLUMNS.filter(c => visibleCols.includes(c.key)),
  ]

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(0,0,0,0.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        padding: '16px',
      }}
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        style={{
          background: '#fff', borderRadius: '12px',
          width: step === 'preview' ? 'min(1200px, 96vw)' : '520px',
          maxHeight: '90vh', display: 'flex', flexDirection: 'column',
          boxShadow: '0 20px 60px rgba(0,0,0,0.2)',
          overflow: 'hidden',
        }}
      >
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '18px 20px 14px', borderBottom: '1px solid #f1f5f9',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FileSpreadsheet size={18} color="#2563eb" />
            <span style={{ fontWeight: 700, fontSize: '15px', color: '#1e293b' }}>
              {step === 'config' ? 'Сформировать выгрузку' : 'Предпросмотр и редактирование'}
            </span>
            <span style={{
              fontSize: '11px', padding: '2px 8px', borderRadius: '20px',
              background: step === 'config' ? '#eff6ff' : '#f0fdf4',
              color: step === 'config' ? '#2563eb' : '#16a34a', fontWeight: 600,
            }}>
              {step === 'config' ? 'Шаг 1 из 2' : 'Шаг 2 из 2'}
            </span>
          </div>
          <button
            onClick={onClose}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#94a3b8', padding: '4px' }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: step === 'preview' ? '0' : '20px' }}>
          {step === 'config' ? (
            <ConfigStep
              sections={sections}
              selectedIds={selectedIds}
              rowTypeOpt={rowTypeOpt}
              visibleCols={visibleCols}
              onToggleSection={toggleSection}
              onSetRowType={setRowTypeOpt}
              onToggleCol={toggleCol}
            />
          ) : (
            <PreviewStep
              rows={rows}
              cols={previewCols}
              showSection={showSection}
              onToggleSection={() => setShowSection(v => !v)}
              onUpdateCell={updateCell}
              onDeleteRow={deleteRow}
            />
          )}
        </div>

        {/* Footer */}
        <div style={{
          padding: '14px 20px', borderTop: '1px solid #f1f5f9',
          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
          gap: '8px',
        }}>
          {step === 'config' ? (
            <>
              <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                {selectedIds.length === 0 ? 'Все разделы' : `${selectedIds.length} разд.`}
                {' · '}
                {rowTypeOpt === 'both' ? 'Работы и материалы' : rowTypeOpt === 'work' ? 'Только работы' : 'Только материалы'}
                {' · '}
                {visibleCols.length} из {ALL_COLUMNS.length} столбцов
              </span>
              <button
                onClick={handleNext}
                disabled={visibleCols.length === 0}
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  padding: '8px 18px', fontSize: '13px', fontWeight: 600,
                  borderRadius: '8px', border: 'none',
                  background: visibleCols.length > 0 ? '#2563eb' : '#e2e8f0',
                  color: visibleCols.length > 0 ? '#fff' : '#94a3b8',
                  cursor: visibleCols.length > 0 ? 'pointer' : 'not-allowed',
                }}
              >
                Далее <ArrowRight size={14} />
              </button>
            </>
          ) : (
            <>
              <button
                onClick={() => setStep('config')}
                style={{
                  display: 'flex', alignItems: 'center', gap: '6px',
                  padding: '8px 16px', fontSize: '13px', fontWeight: 500,
                  borderRadius: '8px', border: '1px solid #e2e8f0',
                  background: '#fff', color: '#374151', cursor: 'pointer',
                }}
              >
                <ArrowLeft size={14} /> Назад
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '12px', color: '#94a3b8' }}>
                  {rows.length} строк
                </span>
                <button
                  onClick={handleDownload}
                  disabled={downloading || rows.length === 0}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '6px',
                    padding: '8px 18px', fontSize: '13px', fontWeight: 600,
                    borderRadius: '8px', border: 'none',
                    background: rows.length > 0 ? '#16a34a' : '#e2e8f0',
                    color: rows.length > 0 ? '#fff' : '#94a3b8',
                    cursor: rows.length > 0 && !downloading ? 'pointer' : 'not-allowed',
                  }}
                >
                  {downloading ? <LumaSpin size="sm" color="#fff" /> : <Download size={14} />}
                  Скачать Excel
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Config Step ──────────────────────────────────────────────────────────────

interface ConfigStepProps {
  sections: SectionTab[]
  selectedIds: string[]
  rowTypeOpt: RowTypeOption
  visibleCols: string[]
  onToggleSection: (id: string) => void
  onSetRowType: (v: RowTypeOption) => void
  onToggleCol: (key: string) => void
}

const ConfigStep: React.FC<ConfigStepProps> = ({
  sections, selectedIds, rowTypeOpt, visibleCols,
  onToggleSection, onSetRowType, onToggleCol,
}) => {
  const labelStyle: React.CSSProperties = {
    fontSize: '12px', fontWeight: 600, color: '#64748b',
    textTransform: 'uppercase', letterSpacing: '0.5px', marginBottom: '8px',
  }
  const sectionStyle: React.CSSProperties = {
    marginBottom: '20px',
  }

  return (
    <div>
      {/* Sections */}
      <div style={sectionStyle}>
        <div style={labelStyle}>Разделы</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
          {sections.map(sec => {
            const active = selectedIds.includes(sec.card_id)
            return (
              <button
                key={sec.card_id}
                onClick={() => onToggleSection(sec.card_id)}
                style={{
                  padding: '5px 12px', fontSize: '13px', borderRadius: '20px',
                  border: active ? '2px solid #2563eb' : '1px solid #e2e8f0',
                  background: active ? '#eff6ff' : '#f8fafc',
                  color: active ? '#2563eb' : '#374151',
                  fontWeight: active ? 600 : 400, cursor: 'pointer',
                  transition: 'all 0.12s',
                }}
              >
                {sec.card_name}
              </button>
            )
          })}
        </div>
        {selectedIds.length === 0 && (
          <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '6px' }}>
            Ничего не выбрано — будут включены все разделы
          </div>
        )}
      </div>

      {/* Row types */}
      <div style={sectionStyle}>
        <div style={labelStyle}>Тип строк</div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {([
            ['both', 'Работы и материалы'],
            ['work', 'Только работы'],
            ['material', 'Только материалы'],
          ] as [RowTypeOption, string][]).map(([val, label]) => (
            <button
              key={val}
              onClick={() => onSetRowType(val)}
              style={{
                padding: '6px 14px', fontSize: '13px', borderRadius: '8px',
                border: rowTypeOpt === val ? '2px solid #2563eb' : '1px solid #e2e8f0',
                background: rowTypeOpt === val ? '#eff6ff' : '#f8fafc',
                color: rowTypeOpt === val ? '#2563eb' : '#374151',
                fontWeight: rowTypeOpt === val ? 600 : 400, cursor: 'pointer',
                transition: 'all 0.12s',
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Columns */}
      <div style={sectionStyle}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '8px' }}>
          <div style={labelStyle}>Столбцы</div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              onClick={() => ALL_COLUMNS.forEach(c => !visibleCols.includes(c.key) && onToggleCol(c.key))}
              style={{ fontSize: '11px', color: '#2563eb', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            >
              Выбрать все
            </button>
            <span style={{ color: '#e2e8f0' }}>|</span>
            <button
              onClick={() => visibleCols.forEach(k => onToggleCol(k))}
              style={{ fontSize: '11px', color: '#64748b', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
            >
              Снять все
            </button>
          </div>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
          {ALL_COLUMNS.map(col => {
            const active = visibleCols.includes(col.key)
            return (
              <button
                key={col.key}
                onClick={() => onToggleCol(col.key)}
                style={{
                  padding: '5px 12px', fontSize: '13px', borderRadius: '20px',
                  border: active ? '2px solid #7c3aed' : '1px solid #e2e8f0',
                  background: active ? '#f5f3ff' : '#f8fafc',
                  color: active ? '#7c3aed' : '#94a3b8',
                  fontWeight: active ? 600 : 400, cursor: 'pointer',
                  transition: 'all 0.12s',
                  textDecoration: active ? 'none' : 'line-through',
                }}
              >
                {col.label}
              </button>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Preview Step ─────────────────────────────────────────────────────────────

interface PreviewStepProps {
  rows: ExportRow[]
  cols: ColDef[]
  showSection: boolean
  onToggleSection: () => void
  onUpdateCell: (rowIdx: number, key: keyof ExportRow, raw: string) => void
  onDeleteRow: (idx: number) => void
}

const PreviewStep: React.FC<PreviewStepProps> = ({
  rows, cols, showSection, onToggleSection, onUpdateCell, onDeleteRow,
}) => {
  const thStyle: React.CSSProperties = {
    padding: '8px 10px', fontSize: '12px', fontWeight: 700,
    color: '#fff', background: '#334155', textAlign: 'left',
    whiteSpace: 'nowrap', position: 'sticky', top: 0, zIndex: 1,
    borderRight: '1px solid #475569',
  }
  const tdStyle: React.CSSProperties = {
    padding: '0', borderBottom: '1px solid #f1f5f9',
    borderRight: '1px solid #f1f5f9',
  }
  const inputStyle: React.CSSProperties = {
    width: '100%', border: 'none', outline: 'none',
    padding: '6px 10px', fontSize: '13px', background: 'transparent',
    boxSizing: 'border-box',
  }

  if (rows.length === 0) {
    return (
      <div style={{ padding: '40px', textAlign: 'center', color: '#94a3b8' }}>
        Нет строк по выбранным фильтрам
      </div>
    )
  }

  return (
    <div>
      {/* Toolbar above table */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '8px',
        padding: '10px 16px', borderBottom: '1px solid #f1f5f9', background: '#f8fafc',
      }}>
        <button
          onClick={onToggleSection}
          style={{
            padding: '4px 10px', fontSize: '12px', borderRadius: '6px',
            border: showSection ? '2px solid #2563eb' : '1px solid #e2e8f0',
            background: showSection ? '#eff6ff' : '#fff',
            color: showSection ? '#2563eb' : '#64748b',
            cursor: 'pointer', fontWeight: showSection ? 600 : 400,
          }}
        >
          {showSection ? '✓ ' : ''}Показать раздел
        </button>
        <span style={{ fontSize: '12px', color: '#94a3b8' }}>
          Ячейки редактируемы — кликните для изменения
        </span>
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto', overflowY: 'auto', maxHeight: 'calc(90vh - 220px)' }}>
        <table style={{ borderCollapse: 'collapse', width: '100%', tableLayout: 'fixed' }}>
          <colgroup>
            {cols.map(c => <col key={c.key} style={{ width: c.width }} />)}
            <col style={{ width: 36 }} />
          </colgroup>
          <thead>
            <tr>
              {cols.map(c => <th key={c.key} style={thStyle}>{c.label}</th>)}
              <th style={{ ...thStyle, width: 36, textAlign: 'center' }} />
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rIdx) => (
              <tr
                key={row._id + rIdx}
                style={{ background: rIdx % 2 === 0 ? '#fff' : '#fafafa' }}
              >
                {cols.map(col => {
                  const key = col.key as keyof ExportRow
                  const val = row[key]
                  const display = col.isNumber ? fmtNum(val as number | null) : (val ?? '')
                  return (
                    <td key={col.key} style={tdStyle}>
                      <input
                        style={{
                          ...inputStyle,
                          textAlign: col.isNumber ? 'right' : 'left',
                          color: col.isNumber && val == null ? '#cbd5e1' : '#1e293b',
                          fontFamily: col.isNumber ? 'monospace' : 'inherit',
                        }}
                        defaultValue={String(display)}
                        key={String(display)}
                        onBlur={e => onUpdateCell(rIdx, key, e.target.value)}
                        title={col.isNumber ? 'Введите число' : undefined}
                      />
                    </td>
                  )
                })}
                <td style={{ ...tdStyle, textAlign: 'center', verticalAlign: 'middle' }}>
                  <button
                    onClick={() => onDeleteRow(rIdx)}
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      color: '#fca5a5', fontSize: '16px', lineHeight: 1,
                      padding: '4px 6px',
                    }}
                    title="Удалить строку"
                  >
                    ×
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default CustomExportModal
