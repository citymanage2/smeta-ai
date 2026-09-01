import React from 'react'
import { SummaryOverrides, SummaryCalcResult, CustomCostRow, FIXED_ROW_KEYS, TargetBasis, TaxSide } from '../../types/summary'
import { deviationColor, fmtDeviationPct as fmtPct, fmtSignedMoney as fmtSigned } from '../../utils/targets'

interface Props {
  calc: SummaryCalcResult
  overrides: SummaryOverrides
  onUpdateOverride: <K extends keyof SummaryOverrides>(key: K, value: SummaryOverrides[K]) => void
  onUpdateSectionTaxPct: (sectionIndex: number, side: TaxSide, taxPct: number) => void
  /** Цель раздела; null — цель снята. */
  onUpdateSectionTarget: (sectionIndex: number, side: TaxSide, target: number | null) => void
}

const fmt = (n: number) =>
  n === 0 ? '—' : Math.round(n).toLocaleString('ru-RU') + ' ₽'

const fmtVal = (n: number) =>
  Math.round(n).toLocaleString('ru-RU') + ' ₽'

// ── Цели оптимизации ─────────────────────────────────────────────────────────

function Deviation({ value, pct }: { value: number | null; pct: number | null }) {
  if (value === null) return null
  return (
    <div style={{ fontSize: '11px', fontWeight: 600, color: deviationColor(value) }}>
      {fmtSigned(value)}
      {pct !== null && <span style={{ fontWeight: 400 }}> · {fmtPct(pct)}</span>}
    </div>
  )
}

/**
 * Ячейка цели: пустая — «цели нет», и это не то же самое, что цель 0.
 * Поэтому пустая строка при вводе снимает цель, а не превращается в ноль.
 */
function TargetInput({
  value, onCommit,
}: {
  value: number | null
  onCommit: (v: number | null) => void
}) {
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState(value === null ? '' : String(value))
  const inputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    if (editing && inputRef.current) { inputRef.current.focus(); inputRef.current.select() }
  }, [editing])
  React.useEffect(() => {
    if (!editing) setDraft(value === null ? '' : String(value))
  }, [value, editing])

  const commit = () => {
    const trimmed = draft.trim()
    if (trimmed === '') onCommit(null)
    else {
      const parsed = parseFloat(trimmed.replace(',', '.'))
      if (!isNaN(parsed) && parsed >= 0) onCommit(parsed)
    }
    setEditing(false)
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') { setDraft(value === null ? '' : String(value)); setEditing(false) }
        }}
        placeholder="нет цели"
        style={{ width: '100px', padding: '2px 6px', fontSize: '13px', border: '1.5px solid #3b82f6', borderRadius: '4px', outline: 'none', textAlign: 'right' }}
      />
    )
  }

  return (
    <span
      onClick={() => setEditing(true)}
      title={value === null ? 'Цель не задана — нажмите, чтобы задать' : 'Нажмите, чтобы изменить цель'}
      style={{
        cursor: 'pointer', padding: '2px 6px', borderRadius: '4px',
        border: '1px dashed #cbd5e1', fontSize: '13px',
        color: value === null ? '#94a3b8' : '#1e293b',
        userSelect: 'none', display: 'inline-block', minWidth: '76px', textAlign: 'right',
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#93c5fd' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#cbd5e1' }}
    >
      {value === null ? '—' : fmtVal(value)}
    </span>
  )
}

// ── NumberInput ──────────────────────────────────────────────────────────────

interface NumberInputProps {
  value: number
  onCommit: (v: number) => void
  suffix?: string
  min?: number
}

function NumberInput({ value, onCommit, suffix = '', min = 0 }: NumberInputProps) {
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState(String(value))
  const inputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    if (editing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [editing])

  React.useEffect(() => {
    if (!editing) setDraft(String(value))
  }, [value, editing])

  const commit = () => {
    const parsed = parseFloat(draft)
    if (!isNaN(parsed) && parsed >= min) onCommit(parsed)
    else setDraft(String(value))
    setEditing(false)
  }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') { setDraft(String(value)); setEditing(false) }
        }}
        style={{ width: '90px', padding: '2px 6px', fontSize: '13px', border: '1.5px solid #3b82f6', borderRadius: '4px', outline: 'none', textAlign: 'right' }}
      />
    )
  }

  return (
    <span
      onClick={() => setEditing(true)}
      title="Нажмите для редактирования"
      style={{
        cursor: 'pointer', padding: '2px 6px', borderRadius: '4px',
        border: '1px dashed #cbd5e1', fontSize: '13px',
        color: value === 0 ? '#94a3b8' : '#1e293b',
        userSelect: 'none', display: 'inline-block', minWidth: '60px', textAlign: 'right',
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#93c5fd' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#cbd5e1' }}
    >
      {value === 0 ? `0${suffix}` : `${value}${suffix}`}
    </span>
  )
}

// ── InlineTextInput ──────────────────────────────────────────────────────────

function InlineTextInput({
  value, onCommit, placeholder, style,
}: {
  value: string
  onCommit: (v: string) => void
  placeholder?: string
  style?: React.CSSProperties
}) {
  const [editing, setEditing] = React.useState(false)
  const [draft, setDraft] = React.useState(value)
  const inputRef = React.useRef<HTMLInputElement>(null)

  React.useEffect(() => {
    if (editing && inputRef.current) { inputRef.current.focus(); inputRef.current.select() }
  }, [editing])
  React.useEffect(() => { if (!editing) setDraft(value) }, [value, editing])

  const commit = () => { onCommit(draft.trim()); setEditing(false) }

  if (editing) {
    return (
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') { setDraft(value); setEditing(false) }
        }}
        style={{ width: '100%', padding: '2px 4px', fontSize: '13px', border: '1.5px solid #3b82f6', borderRadius: '4px', outline: 'none', ...style }}
      />
    )
  }

  return (
    <span
      onClick={() => setEditing(true)}
      title="Нажмите для редактирования"
      style={{
        cursor: 'pointer', display: 'block', padding: '2px 4px', borderRadius: '4px',
        border: '1px dashed transparent', fontSize: '13px',
        color: value ? '#1e293b' : '#94a3b8', userSelect: 'none', minWidth: '40px',
        ...style,
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#cbd5e1' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'transparent' }}
    >
      {value || placeholder || '—'}
    </span>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────

const thStyle: React.CSSProperties = {
  padding: '8px 8px', fontSize: '11px', fontWeight: 700, color: '#64748b',
  textTransform: 'uppercase', letterSpacing: '0.04em', textAlign: 'left',
  borderBottom: '2px solid #e2e8f0', whiteSpace: 'nowrap', background: '#f8fafc',
}
const th = (extra?: React.CSSProperties): React.CSSProperties => ({ ...thStyle, ...extra })

const tdBase: React.CSSProperties = {
  padding: '5px 8px', fontSize: '13px', color: '#374151',
  borderBottom: '1px solid #f1f5f9', verticalAlign: 'middle',
}
const td = (extra?: React.CSSProperties): React.CSSProperties => ({ ...tdBase, ...extra })
const tdR = (extra?: React.CSSProperties): React.CSSProperties => ({ ...tdBase, textAlign: 'right', ...extra })

const tdBoldBase: React.CSSProperties = { ...tdBase, fontWeight: 700, color: '#0f172a', background: '#f8fafc' }
const tdB = (extra?: React.CSSProperties): React.CSSProperties => ({ ...tdBoldBase, ...extra })
const tdBR = (extra?: React.CSSProperties): React.CSSProperties => ({ ...tdBoldBase, textAlign: 'right', ...extra })

// ── DeleteButton ─────────────────────────────────────────────────────────────

function DeleteButton({ onClick, visible }: { onClick: () => void; visible: boolean }) {
  return (
    <td
      style={{
        ...tdBase, width: '24px', padding: '2px 4px', textAlign: 'center',
        opacity: visible ? 1 : 0, transition: 'opacity 0.15s',
      }}
    >
      <button
        onClick={(e) => { e.stopPropagation(); onClick() }}
        title="Удалить строку"
        style={{
          width: '18px', height: '18px', borderRadius: '50%', border: 'none',
          background: '#fee2e2', color: '#dc2626', cursor: 'pointer',
          fontSize: '11px', lineHeight: 1, display: 'inline-flex',
          alignItems: 'center', justifyContent: 'center', padding: 0,
        }}
      >
        ×
      </button>
    </td>
  )
}

// ── AddRowButton ─────────────────────────────────────────────────────────────

function AddRowButton({ onClick, label }: { onClick: () => void; label: string }) {
  return (
    <tr>
      <td colSpan={6} style={{ padding: '4px 8px', borderBottom: '1px solid #f1f5f9' }}>
        <button
          onClick={onClick}
          style={{
            display: 'flex', alignItems: 'center', gap: '4px',
            background: 'none', border: '1px dashed #cbd5e1', borderRadius: '6px',
            padding: '3px 10px', cursor: 'pointer', fontSize: '12px',
            color: '#64748b', transition: 'all 0.15s',
          }}
          onMouseEnter={(e) => {
            const el = e.currentTarget as HTMLElement
            el.style.borderColor = '#3b82f6'
            el.style.color = '#3b82f6'
          }}
          onMouseLeave={(e) => {
            const el = e.currentTarget as HTMLElement
            el.style.borderColor = '#cbd5e1'
            el.style.color = '#64748b'
          }}
        >
          + {label}
        </button>
      </td>
    </tr>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

const SummarySheet: React.FC<Props> = ({
  calc, overrides, onUpdateOverride, onUpdateSectionTaxPct, onUpdateSectionTarget,
}) => {
  const [hoveredRow, setHoveredRow] = React.useState<string | null>(null)

  const hidden = new Set(overrides.hidden_fixed_rows ?? [])
  const customBefore = overrides.custom_rows_before ?? []
  const customAfter = overrides.custom_rows_after ?? []

  // Numbering: visible fixed rows get 1,2,3...; custom_before continue after
  const visibleFixed = FIXED_ROW_KEYS.filter(k => !hidden.has(k))
  const customBeforeStartNum = visibleFixed.length + 1

  const hideFixed = (key: string) => {
    onUpdateOverride('hidden_fixed_rows', [...(overrides.hidden_fixed_rows ?? []), key])
  }

  const addCustomBefore = () => {
    const newRow: CustomCostRow = {
      id: crypto.randomUUID(),
      label: '',
      qty_pct: '',
      without_vat: 0,
    }
    onUpdateOverride('custom_rows_before', [...customBefore, newRow])
  }

  const addCustomAfter = () => {
    const newRow: CustomCostRow = {
      id: crypto.randomUUID(),
      label: '',
      qty_pct: '',
      without_vat: 0,
    }
    onUpdateOverride('custom_rows_after', [...customAfter, newRow])
  }

  const deleteCustomBefore = (id: string) => {
    onUpdateOverride('custom_rows_before', customBefore.filter(r => r.id !== id))
  }

  const deleteCustomAfter = (id: string) => {
    onUpdateOverride('custom_rows_after', customAfter.filter(r => r.id !== id))
  }

  const updateCustomBefore = (id: string, changes: Partial<CustomCostRow>) => {
    onUpdateOverride('custom_rows_before', customBefore.map(r => r.id === id ? { ...r, ...changes } : r))
  }

  const updateCustomAfter = (id: string, changes: Partial<CustomCostRow>) => {
    onUpdateOverride('custom_rows_after', customAfter.map(r => r.id === id ? { ...r, ...changes } : r))
  }

  // ── Fixed row data ──────────────────────────────────────────────────────────
  const fixedRows: {
    key: string
    label: string
    editCell?: React.ReactNode
    withVat: number
    withoutVat: number
    isManual?: boolean
    manualKey?: keyof SummaryOverrides
  }[] = [
    { key: 'works', label: 'Работы', withVat: calc.works_with_vat, withoutVat: calc.works_without_vat },
    { key: 'materials', label: 'Материалы', withVat: calc.materials_with_vat, withoutVat: calc.materials_without_vat },
    {
      key: 'transport', label: 'Транспортные расходы', withVat: calc.transport_with_vat, withoutVat: calc.transport_without_vat,
      editCell: <NumberInput value={overrides.transport_pct} onCommit={(v) => onUpdateOverride('transport_pct', v)} suffix="%" />,
    },
    {
      key: 'cleanup', label: 'Уборка и вывоз мусора', withVat: calc.cleanup_with_vat, withoutVat: calc.cleanup_without_vat,
      editCell: <NumberInput value={overrides.cleanup_pct} onCommit={(v) => onUpdateOverride('cleanup_pct', v)} suffix="%" />,
    },
    {
      key: 'overhead', label: 'Накладные', withVat: calc.overhead_with_vat, withoutVat: calc.overhead_without_vat,
      editCell: <NumberInput value={overrides.overhead_pct} onCommit={(v) => onUpdateOverride('overhead_pct', v)} suffix="%" />,
    },
    {
      key: 'daily_workers', label: 'Разнорабочие ежедневно', withVat: calc.daily_workers_with_vat, withoutVat: calc.daily_workers_without_vat,
      editCell: <NumberInput value={overrides.daily_workers_cost} onCommit={(v) => onUpdateOverride('daily_workers_cost', v)} suffix=" чел" />,
    },
    { key: 'bank_guarantee', label: 'Банковская гарантия', withVat: calc.bank_guarantee_with_vat, withoutVat: calc.bank_guarantee_without_vat, isManual: true, manualKey: 'bank_guarantee_cost' },
    { key: 'cleaning', label: 'Клининг', withVat: calc.cleaning_with_vat, withoutVat: calc.cleaning_without_vat, isManual: true, manualKey: 'cleaning_cost' },
    { key: 'ppr', label: 'Рабочая документация (ППР)', withVat: calc.ppr_with_vat, withoutVat: calc.ppr_without_vat, isManual: true, manualKey: 'ppr_cost' },
    { key: 'commissioning', label: 'Разнорабочие мусор', withVat: calc.commissioning_with_vat, withoutVat: calc.commissioning_without_vat, isManual: true, manualKey: 'commissioning_cost' },
    { key: 'construction_control', label: 'Строительный контроль', withVat: calc.construction_control_with_vat, withoutVat: calc.construction_control_without_vat, isManual: true, manualKey: 'construction_control_cost' },
    { key: 'author_supervision', label: 'Авторский надзор', withVat: calc.author_supervision_with_vat, withoutVat: calc.author_supervision_without_vat, isManual: true, manualKey: 'author_supervision_cost' },
    { key: 'passes', label: 'Пропуски, корочки', withVat: calc.passes_with_vat, withoutVat: calc.passes_without_vat, isManual: true, manualKey: 'passes_cost' },
    { key: 'site_office', label: 'Бытовка', withVat: calc.site_office_with_vat, withoutVat: calc.site_office_without_vat, isManual: true, manualKey: 'site_office_cost' },
    { key: 'travel', label: 'Командировочные', withVat: calc.travel_with_vat, withoutVat: calc.travel_without_vat, isManual: true, manualKey: 'travel_cost' },
    { key: 'rp', label: 'РП', withVat: calc.rp_with_vat, withoutVat: calc.rp_without_vat, isManual: true, manualKey: 'rp_cost' },
    { key: 'housing_rent', label: 'Аренда жилья', withVat: calc.housing_rent_with_vat, withoutVat: calc.housing_rent_without_vat, isManual: true, manualKey: 'housing_rent_cost' },
    { key: 'workers_transport', label: 'Транспортные расходы люди', withVat: calc.workers_transport_with_vat, withoutVat: calc.workers_transport_without_vat, isManual: true, manualKey: 'workers_transport_cost' },
  ]

  let visibleNum = 0

  return (
    <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>

      {/* ── Left table ─────────────────────────────────────────────────────── */}
      <div style={{ flex: '1 1 640px', minWidth: 0 }}>
        <div style={{ fontSize: '12px', fontWeight: 700, color: '#7c3aed', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
          Себестоимость и цена для заказчика
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '28px' }} />
              <col />
              <col style={{ width: '100px' }} />
              <col style={{ width: '150px' }} />
              <col style={{ width: '150px' }} />
              <col style={{ width: '28px' }} />
            </colgroup>
            <thead>
              <tr>
                <th style={th({ textAlign: 'center' })}>№</th>
                <th style={th()}>Наименование</th>
                <th style={th({ textAlign: 'center' })}>%&nbsp;/&nbsp;Кол-во</th>
                <th style={th({ textAlign: 'right' })}>Стоимость с НДС</th>
                <th style={th({ textAlign: 'right' })}>Стоимость без НДС</th>
                <th style={{ ...thStyle, padding: 0, width: '28px' }} />
              </tr>
            </thead>
            <tbody>

              {/* Коэффициент */}
              <tr
                style={{ background: '#faf5ff' }}
                onMouseEnter={() => setHoveredRow('coeff')}
                onMouseLeave={() => setHoveredRow(null)}
              >
                <td style={td({ textAlign: 'center' })} />
                <td style={td({ fontWeight: 600, color: '#7c3aed' })}>
                  Коэффициент к ценам
                  <span style={{ marginLeft: 6, fontSize: '11px', fontWeight: 400, color: '#9ca3af' }}>(×все цены)</span>
                </td>
                <td style={tdR()}>
                  <NumberInput value={overrides.coefficient} onCommit={(v) => onUpdateOverride('coefficient', v)} min={0.01} />
                </td>
                <td style={tdR()} /><td style={tdR()} />
                <td style={td({ width: 28, padding: '2px 4px' })} />
              </tr>

              {/* Fixed rows */}
              {fixedRows.map((row) => {
                if (hidden.has(row.key)) return null
                visibleNum++
                const num = visibleNum
                const rowId = `fixed-${row.key}`
                const isHovered = hoveredRow === rowId

                if (row.isManual && row.manualKey) {
                  const storedWithout = overrides[row.manualKey] as number
                  return (
                    <tr
                      key={row.key}
                      onMouseEnter={() => setHoveredRow(rowId)}
                      onMouseLeave={() => setHoveredRow(null)}
                    >
                      <td style={td({ textAlign: 'center', color: '#94a3b8', fontSize: '12px' })}>{num}</td>
                      <td style={td()}>{row.label}</td>
                      <td style={tdR()} />
                      <td style={tdR()}>
                        <NumberInput
                          value={Math.round(row.withVat)}
                          onCommit={(v) => onUpdateOverride(row.manualKey!, v / 1.22)}
                          suffix=" ₽"
                        />
                      </td>
                      <td style={tdR({ color: '#64748b' })}>
                        <NumberInput
                          value={Math.round(storedWithout)}
                          onCommit={(v) => onUpdateOverride(row.manualKey!, v)}
                          suffix=" ₽"
                        />
                      </td>
                      <DeleteButton onClick={() => hideFixed(row.key)} visible={isHovered} />
                    </tr>
                  )
                }

                return (
                  <tr
                    key={row.key}
                    onMouseEnter={() => setHoveredRow(rowId)}
                    onMouseLeave={() => setHoveredRow(null)}
                  >
                    <td style={td({ textAlign: 'center', color: '#94a3b8', fontSize: '12px' })}>{num}</td>
                    <td style={td()}>{row.label}</td>
                    <td style={tdR()}>{row.editCell ?? null}</td>
                    <td style={tdR()}>{row.withVat === 0 ? '—' : fmtVal(row.withVat)}</td>
                    <td style={tdR({ color: '#64748b' })}>{row.withoutVat === 0 ? '—' : fmtVal(row.withoutVat)}</td>
                    <DeleteButton onClick={() => hideFixed(row.key)} visible={isHovered} />
                  </tr>
                )
              })}

              {/* Custom rows before separator */}
              {customBefore.map((cr, idx) => {
                const num = customBeforeStartNum + idx
                const rowId = `custom-before-${cr.id}`
                const isHovered = hoveredRow === rowId
                const withVat = cr.without_vat * 1.22
                return (
                  <tr
                    key={cr.id}
                    onMouseEnter={() => setHoveredRow(rowId)}
                    onMouseLeave={() => setHoveredRow(null)}
                  >
                    <td style={td({ textAlign: 'center', color: '#94a3b8', fontSize: '12px' })}>{num}</td>
                    <td style={td()}>
                      <InlineTextInput
                        value={cr.label}
                        onCommit={(v) => updateCustomBefore(cr.id, { label: v })}
                        placeholder="Наименование"
                      />
                    </td>
                    <td style={tdR()}>
                      <InlineTextInput
                        value={cr.qty_pct}
                        onCommit={(v) => updateCustomBefore(cr.id, { qty_pct: v })}
                        placeholder="—"
                        style={{ textAlign: 'right' }}
                      />
                    </td>
                    <td style={tdR()}>
                      <NumberInput
                        value={Math.round(withVat)}
                        onCommit={(v) => updateCustomBefore(cr.id, { without_vat: v / 1.22 })}
                        suffix=" ₽"
                      />
                    </td>
                    <td style={tdR({ color: '#64748b' })}>
                      <NumberInput
                        value={Math.round(cr.without_vat)}
                        onCommit={(v) => updateCustomBefore(cr.id, { without_vat: v })}
                        suffix=" ₽"
                      />
                    </td>
                    <DeleteButton onClick={() => deleteCustomBefore(cr.id)} visible={isHovered} />
                  </tr>
                )
              })}

              <AddRowButton onClick={addCustomBefore} label="Добавить строку" />

              {/* Separator */}
              <tr><td colSpan={6} style={{ height: '4px', background: '#e2e8f0', padding: 0 }} /></tr>

              {/* ИТОГО себестоимость */}
              <tr style={{ background: '#f1f5f9' }}>
                <td style={tdB({ textAlign: 'center', color: '#94a3b8' })} />
                <td style={tdB()}>ИТОГО себестоимость объекта</td>
                <td style={tdBR()} />
                <td style={tdBR()}>{fmtVal(calc.subtotal_with_vat)}</td>
                <td style={tdBR()}>{fmtVal(calc.subtotal_without_vat)}</td>
                <td style={tdB({ width: 28, padding: '2px 4px' })} />
              </tr>

              {/* Custom rows after separator (unnumbered, informational) */}
              {customAfter.map((cr) => {
                const rowId = `custom-after-${cr.id}`
                const isHovered = hoveredRow === rowId
                const withVat = cr.without_vat * 1.22
                return (
                  <tr
                    key={cr.id}
                    style={{ background: '#fffbeb' }}
                    onMouseEnter={() => setHoveredRow(rowId)}
                    onMouseLeave={() => setHoveredRow(null)}
                  >
                    <td style={td({ textAlign: 'center', color: '#94a3b8', fontSize: '12px' })} />
                    <td style={td()}>
                      <InlineTextInput
                        value={cr.label}
                        onCommit={(v) => updateCustomAfter(cr.id, { label: v })}
                        placeholder="Наименование"
                      />
                    </td>
                    <td style={tdR()}>
                      <InlineTextInput
                        value={cr.qty_pct}
                        onCommit={(v) => updateCustomAfter(cr.id, { qty_pct: v })}
                        placeholder="—"
                        style={{ textAlign: 'right' }}
                      />
                    </td>
                    <td style={tdR()}>
                      <NumberInput
                        value={Math.round(withVat)}
                        onCommit={(v) => updateCustomAfter(cr.id, { without_vat: v / 1.22 })}
                        suffix=" ₽"
                      />
                    </td>
                    <td style={tdR({ color: '#64748b' })}>
                      <NumberInput
                        value={Math.round(cr.without_vat)}
                        onCommit={(v) => updateCustomAfter(cr.id, { without_vat: v })}
                        suffix=" ₽"
                      />
                    </td>
                    <DeleteButton onClick={() => deleteCustomAfter(cr.id)} visible={isHovered} />
                  </tr>
                )
              })}

              <AddRowButton onClick={addCustomAfter} label="Добавить строку (без номера)" />

              {/* Непредвиденные расходы */}
              <tr
                onMouseEnter={() => setHoveredRow('contingency')}
                onMouseLeave={() => setHoveredRow(null)}
              >
                <td style={td({ textAlign: 'center' })} />
                <td style={td()}>Непредвиденные расходы</td>
                <td style={tdR()}>
                  <NumberInput value={overrides.contingency_pct} onCommit={(v) => onUpdateOverride('contingency_pct', v)} suffix="%" />
                </td>
                <td style={tdR()}>{fmt(calc.contingency_with_vat)}</td>
                <td style={tdR({ color: '#64748b' })}>{fmt(calc.contingency_without_vat)}</td>
                <td style={td({ width: 28 })} />
              </tr>

              {/* Плановая прибыль — merged */}
              <tr>
                <td style={td({ textAlign: 'center' })} />
                <td style={td()}>Плановая прибыль (без НДС)</td>
                <td style={tdR()}>
                  <NumberInput value={overrides.profit_pct} onCommit={(v) => onUpdateOverride('profit_pct', v)} suffix="%" />
                </td>
                <td style={tdR({ color: '#059669', fontWeight: 600 })} colSpan={2}>{fmtVal(calc.profit)}</td>
                <td style={td({ width: 28 })} />
              </tr>

              {/* Полная себестоимость — merged */}
              <tr style={{ background: '#f1f5f9' }}>
                <td style={tdB({ textAlign: 'center', color: '#94a3b8' })} />
                <td style={tdB()}>Полная себестоимость с учётом прибыли и непредвиденных (без НДС)</td>
                <td style={tdBR()} />
                <td style={tdBR({ fontSize: '14px' })} colSpan={2}>{fmtVal(calc.full_cost_without_vat)}</td>
                <td style={tdB({ width: 28 })} />
              </tr>

              {/* НДС — merged */}
              <tr>
                <td style={td({ textAlign: 'center' })} />
                <td style={td()}>НДС от полной себестоимости</td>
                <td style={tdR()}>
                  <NumberInput value={overrides.vat_full_cost_pct} onCommit={(v) => onUpdateOverride('vat_full_cost_pct', v)} suffix="%" />
                </td>
                <td style={tdR()} colSpan={2}>{fmt(calc.vat)}</td>
                <td style={td({ width: 28 })} />
              </tr>

              {/* Др. налоги — merged */}
              <tr>
                <td style={td({ textAlign: 'center' })} />
                <td style={td()}>Др. налоги от полной себестоимости</td>
                <td style={tdR()}>
                  <NumberInput value={overrides.tax_pct} onCommit={(v) => onUpdateOverride('tax_pct', v)} suffix="%" />
                </td>
                <td style={tdR()} colSpan={2}>{fmt(calc.other_tax)}</td>
                <td style={td({ width: 28 })} />
              </tr>

              {/* ИТОГО для Заказчика */}
              <tr style={{ background: '#eff6ff' }}>
                <td style={tdB({ textAlign: 'center' })} />
                <td style={tdB({ fontSize: '14px', color: '#2563eb' })}>
                  ИТОГО по смете для Заказчика с учётом налогов
                </td>
                <td style={tdBR()} />
                <td style={tdBR({ fontSize: '16px', color: '#2563eb' })} colSpan={2}>
                  {fmtVal(calc.total_for_customer)}
                </td>
                <td style={tdB({ width: 28 })} />
              </tr>

              {/* Цель по объекту. Строка ввода стоит всегда — иначе цель некуда
                  задать; строка отклонения появляется только вместе с целью. */}
              <tr style={{ background: '#faf5ff' }}>
                <td style={td({ textAlign: 'center' })} />
                <td style={td({ fontWeight: 600, color: '#7c3aed' })}>
                  Цель по объекту
                  <span style={{ marginLeft: 6, fontSize: '11px', fontWeight: 400, color: '#9ca3af' }}>
                    (итог для заказчика)
                  </span>
                </td>
                <td style={tdR()} />
                <td style={tdR()} colSpan={2}>
                  <TargetInput
                    value={calc.target_total_for_customer}
                    onCommit={(v) => onUpdateOverride('target_total_for_customer', v)}
                  />
                </td>
                <td style={td({ width: 28 })} />
              </tr>

              {calc.total_deviation !== null && (
                <tr>
                  <td style={td({ textAlign: 'center' })} />
                  <td style={td()}>Отклонение от цели по объекту</td>
                  <td style={tdR()} />
                  <td style={tdR({ fontWeight: 600, color: deviationColor(calc.total_deviation) })} colSpan={2}>
                    {fmtSigned(calc.total_deviation)}
                    {calc.total_deviation_pct !== null && (
                      <span style={{ fontWeight: 400 }}> · {fmtPct(calc.total_deviation_pct)}</span>
                    )}
                  </td>
                  <td style={td({ width: 28 })} />
                </tr>
              )}

            </tbody>
          </table>
        </div>
      </div>

      {/* ── Right table ─────────────────────────────────────────────────────── */}
      {calc.section_totals.length > 0 && (
        <div style={{ flex: '1 1 640px', minWidth: 0 }}>
          <div style={{ fontSize: '12px', fontWeight: 700, color: '#7c3aed', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px' }}>
            Разбивка по разделам
          </div>
          <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '6px' }}>
            Налог: 0% — подрядчик с НДС (добавляем 22%); 22% — самозанятый (НДС уже в цене).
            У работ и материалов раздела ставки независимы.
          </div>

          {/* Цели оптимизации: база — одна на весь бланк. Переключение не
              трогает сами цифры целей (их вводил человек), а меняет колонку,
              с которой они сравниваются, — поэтому это написано прямо здесь. */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap',
            marginBottom: '8px', fontSize: '12px', color: '#475569',
          }}>
            <span style={{ fontWeight: 600 }}>Цели заданы в:</span>
            {([
              ['cost', 'суммах из сметы (с/с)'],
              ['with_vat', 'суммах с НДС'],
            ] as [TargetBasis, string][]).map(([value, label]) => {
              const active = calc.target_basis === value
              return (
                <button
                  key={value}
                  onClick={() => onUpdateOverride('target_basis', value)}
                  style={{
                    padding: '3px 10px', fontSize: '12px',
                    fontWeight: active ? 600 : 400, borderRadius: '6px',
                    border: active ? '1.5px solid #7c3aed' : '1px solid #e2e8f0',
                    background: active ? '#f5f3ff' : '#fff',
                    color: active ? '#7c3aed' : '#475569', cursor: 'pointer',
                  }}
                >
                  {label}
                </button>
              )
            })}
            <span style={{ color: '#94a3b8' }}>
              переключение меняет только то, с какой колонкой сравнивается цель
            </span>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <colgroup>
                <col />
                <col style={{ width: '130px' }} />
                <col style={{ width: '72px' }} />
                <col style={{ width: '130px' }} />
                <col style={{ width: '130px' }} />
                <col style={{ width: '4px' }} />
                <col style={{ width: '130px' }} />
                <col style={{ width: '72px' }} />
                <col style={{ width: '130px' }} />
                <col style={{ width: '130px' }} />
              </colgroup>
              <thead>
                <tr>
                  <th style={th()}>Раздел</th>
                  <th style={th({ textAlign: 'right' })}>Работы из сметы (с/с)</th>
                  <th style={th({ textAlign: 'center' })}>Налог %</th>
                  <th style={th({ textAlign: 'right' })}>Стоимость работ с НДС</th>
                  <th style={th({ textAlign: 'right' })}>Цель работ / откл.</th>
                  <th style={{ ...thStyle, padding: 0, borderLeft: '2px solid #e2e8f0', background: '#e2e8f0' }} />
                  <th style={th({ textAlign: 'right', borderLeft: '2px solid #e2e8f0' })}>Материалы из сметы (с/с)</th>
                  <th style={th({ textAlign: 'center' })}>Налог %</th>
                  <th style={th({ textAlign: 'right' })}>Стоимость матер. с НДС</th>
                  <th style={th({ textAlign: 'right' })}>Цель матер. / откл.</th>
                </tr>
              </thead>
              <tbody>
                {calc.section_totals.map((sec, idx) => (
                  <tr key={sec.card_id}>
                    <td style={td()}>{sec.card_name}</td>
                    <td style={tdR()}>{fmt(sec.works_raw)}</td>
                    <td style={td({ textAlign: 'center' })}>
                      <NumberInput value={sec.tax_pct_works} onCommit={(v) => onUpdateSectionTaxPct(idx, 'works', v)} suffix="%" />
                    </td>
                    <td style={tdR({ color: sec.tax_pct_works > 0 ? '#059669' : undefined })}>{fmtVal(sec.works_with_vat)}</td>
                    <td style={tdR()}>
                      <TargetInput
                        value={sec.target_works}
                        onCommit={(v) => onUpdateSectionTarget(idx, 'works', v)}
                      />
                      <Deviation value={sec.works_deviation} pct={sec.works_deviation_pct} />
                    </td>
                    <td style={{ padding: 0, borderLeft: '2px solid #e2e8f0', background: '#e2e8f0', borderBottom: '1px solid #f1f5f9' }} />
                    <td style={tdR({ borderLeft: '2px solid #e2e8f0' })}>{fmt(sec.materials_raw)}</td>
                    <td style={td({ textAlign: 'center' })}>
                      <NumberInput value={sec.tax_pct_materials} onCommit={(v) => onUpdateSectionTaxPct(idx, 'materials', v)} suffix="%" />
                    </td>
                    <td style={tdR({ color: sec.tax_pct_materials > 0 ? '#059669' : undefined })}>{fmtVal(sec.materials_with_vat)}</td>
                    <td style={tdR()}>
                      <TargetInput
                        value={sec.target_materials}
                        onCommit={(v) => onUpdateSectionTarget(idx, 'materials', v)}
                      />
                      <Deviation
                        value={sec.materials_deviation}
                        pct={sec.materials_deviation_pct}
                      />
                    </td>
                  </tr>
                ))}
                <tr style={{ background: '#f8fafc' }}>
                  <td style={tdB()}>ИТОГО</td>
                  <td style={tdBR()}>{fmtVal(calc.section_totals.reduce((s, r) => s + r.works_raw, 0))}</td>
                  <td style={tdB()} />
                  <td style={tdBR()}>{fmtVal(calc.works_with_vat)}</td>
                  <td style={tdBR()}>
                    {calc.targets_total_works === null ? '—' : fmtVal(calc.targets_total_works)}
                    <Deviation
                      value={calc.targets_deviation_works}
                      pct={calc.targets_deviation_works_pct}
                    />
                  </td>
                  <td style={{ padding: 0, borderLeft: '2px solid #e2e8f0', background: '#e2e8f0' }} />
                  <td style={tdBR({ borderLeft: '2px solid #e2e8f0' })}>{fmtVal(calc.section_totals.reduce((s, r) => s + r.materials_raw, 0))}</td>
                  <td style={tdB()} />
                  <td style={tdBR()}>{fmtVal(calc.materials_with_vat)}</td>
                  <td style={tdBR()}>
                    {calc.targets_total_materials === null
                      ? '—' : fmtVal(calc.targets_total_materials)}
                    <Deviation
                      value={calc.targets_deviation_materials}
                      pct={calc.targets_deviation_materials_pct}
                    />
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

export default SummarySheet
