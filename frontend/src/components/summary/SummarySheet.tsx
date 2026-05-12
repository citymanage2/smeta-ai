import React from 'react'
import { SummaryOverrides, SummaryCalcResult } from '../../types/summary'

interface Props {
  calc: SummaryCalcResult
  overrides: SummaryOverrides
  onUpdateOverride: <K extends keyof SummaryOverrides>(key: K, value: number) => void
}

const fmt = (n: number) =>
  Math.round(n).toLocaleString('ru-RU') + ' ₽'

const pct = (n: number) => n + '%'

interface NumberInputProps {
  value: number
  onCommit: (v: number) => void
  suffix?: string
  min?: number
}

function NumberInput({ value, onCommit, suffix, min = 0 }: NumberInputProps) {
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
    if (!isNaN(parsed) && parsed >= min) {
      onCommit(parsed)
    } else {
      setDraft(String(value))
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
          if (e.key === 'Escape') { setDraft(String(value)); setEditing(false) }
        }}
        style={{
          width: '80px',
          padding: '2px 6px',
          fontSize: '13px',
          border: '1.5px solid #3b82f6',
          borderRadius: '4px',
          outline: 'none',
          textAlign: 'right',
        }}
      />
    )
  }

  return (
    <span
      onClick={() => setEditing(true)}
      title="Нажмите для редактирования"
      style={{
        cursor: 'pointer',
        padding: '2px 6px',
        borderRadius: '4px',
        border: '1px dashed #cbd5e1',
        fontSize: '13px',
        color: '#1e293b',
        userSelect: 'none',
        display: 'inline-block',
        minWidth: '60px',
        textAlign: 'right',
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#93c5fd' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#cbd5e1' }}
    >
      {value}{suffix}
    </span>
  )
}

const thStyle: React.CSSProperties = {
  padding: '8px 10px',
  fontSize: '11px',
  fontWeight: 700,
  color: '#64748b',
  textTransform: 'uppercase',
  letterSpacing: '0.04em',
  textAlign: 'left',
  borderBottom: '2px solid #e2e8f0',
  whiteSpace: 'nowrap',
  background: '#f8fafc',
}

const tdStyle: React.CSSProperties = {
  padding: '7px 10px',
  fontSize: '13px',
  color: '#374151',
  borderBottom: '1px solid #f1f5f9',
  verticalAlign: 'middle',
}

const tdRight: React.CSSProperties = { ...tdStyle, textAlign: 'right' }

const tdBold: React.CSSProperties = {
  ...tdStyle,
  fontWeight: 700,
  color: '#0f172a',
  background: '#f8fafc',
}

const tdBoldRight: React.CSSProperties = { ...tdBold, textAlign: 'right' }

const SummarySheet: React.FC<Props> = ({ calc, overrides, onUpdateOverride }) => {
  return (
    <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>

      {/* ── Left table: Cost breakdown ── */}
      <div style={{ flex: '1 1 480px', minWidth: 0 }}>
        <div style={{
          fontSize: '12px', fontWeight: 700, color: '#7c3aed',
          textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px',
        }}>
          Себестоимость и цена для заказчика
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed' }}>
            <colgroup>
              <col style={{ width: '30px' }} />
              <col />
              <col style={{ width: '140px' }} />
              <col style={{ width: '160px' }} />
            </colgroup>
            <thead>
              <tr>
                <th style={{ ...thStyle, textAlign: 'center' }}>№</th>
                <th style={thStyle}>Статья</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Значение</th>
                <th style={{ ...thStyle, textAlign: 'right' }}>Сумма</th>
              </tr>
            </thead>
            <tbody>
              <Row num={1} label="Работы (с/с)" value={fmt(calc.works)} />
              <Row num={2} label="Материалы (с/с)" value={fmt(calc.materials)} />
              <Row
                num={3}
                label="Транспортные расходы"
                editCell={
                  <NumberInput
                    value={overrides.transport_pct}
                    onCommit={(v) => onUpdateOverride('transport_pct', v)}
                    suffix="%"
                  />
                }
                value={fmt(calc.transport)}
              />
              <Row
                num={4}
                label="Уборка и вывоз мусора"
                editCell={
                  <NumberInput
                    value={overrides.cleanup_pct}
                    onCommit={(v) => onUpdateOverride('cleanup_pct', v)}
                    suffix="%"
                  />
                }
                value={fmt(calc.cleanup)}
              />
              <Row
                num={5}
                label="Накладные расходы"
                editCell={
                  <NumberInput
                    value={overrides.overhead_pct}
                    onCommit={(v) => onUpdateOverride('overhead_pct', v)}
                    suffix="%"
                  />
                }
                value={fmt(calc.overhead)}
              />
              <Row
                num={6}
                label="Разнорабочие ежедневно"
                editCell={
                  <NumberInput
                    value={overrides.daily_workers_cost}
                    onCommit={(v) => onUpdateOverride('daily_workers_cost', v)}
                    suffix=" ₽"
                  />
                }
                value={fmt(calc.daily_workers)}
              />
              <Row
                num={7}
                label="Банковская гарантия"
                editCell={
                  <NumberInput
                    value={overrides.bank_guarantee_cost}
                    onCommit={(v) => onUpdateOverride('bank_guarantee_cost', v)}
                    suffix=" ₽"
                  />
                }
                value={fmt(calc.bank_guarantee)}
              />
              <Row
                num={8}
                label="Клининг"
                editCell={
                  <NumberInput
                    value={overrides.cleaning_cost}
                    onCommit={(v) => onUpdateOverride('cleaning_cost', v)}
                    suffix=" ₽"
                  />
                }
                value={fmt(calc.cleaning)}
              />
              <Row
                num={9}
                label="РД (ППР), исполнит."
                editCell={
                  <NumberInput
                    value={overrides.ppr_cost}
                    onCommit={(v) => onUpdateOverride('ppr_cost', v)}
                    suffix=" ₽"
                  />
                }
                value={fmt(calc.ppr)}
              />
              <Row
                num={10}
                label="Пусконаладочные"
                editCell={
                  <NumberInput
                    value={overrides.commissioning_cost}
                    onCommit={(v) => onUpdateOverride('commissioning_cost', v)}
                    suffix=" ₽"
                  />
                }
                value={fmt(calc.commissioning)}
              />

              <TotalRow label="ИТОГО Себестоимость" value={fmt(calc.subtotal)} />

              <Row
                label="Непредвиденные расходы"
                editCell={
                  <NumberInput
                    value={overrides.contingency_pct}
                    onCommit={(v) => onUpdateOverride('contingency_pct', v)}
                    suffix="%"
                  />
                }
                value={fmt(calc.contingency)}
              />
              <Row
                label="Плановая прибыль"
                editCell={
                  <NumberInput
                    value={overrides.profit_pct}
                    onCommit={(v) => onUpdateOverride('profit_pct', v)}
                    suffix="%"
                  />
                }
                value={fmt(calc.profit)}
              />

              <TotalRow label="Полная себестоимость" value={fmt(calc.full_cost)} />

              <Row
                label="НДС на работы"
                editCell={
                  <NumberInput
                    value={overrides.vat_works_pct}
                    onCommit={(v) => onUpdateOverride('vat_works_pct', v)}
                    suffix="%"
                  />
                }
                value={fmt((calc.works * overrides.vat_works_pct) / 100)}
              />
              <Row
                label="НДС на материалы"
                editCell={
                  <NumberInput
                    value={overrides.vat_materials_pct}
                    onCommit={(v) => onUpdateOverride('vat_materials_pct', v)}
                    suffix="%"
                  />
                }
                value={fmt((calc.materials * overrides.vat_materials_pct) / 100)}
              />
              <Row
                label="Другие налоги"
                editCell={
                  <NumberInput
                    value={overrides.tax_pct}
                    onCommit={(v) => onUpdateOverride('tax_pct', v)}
                    suffix="%"
                  />
                }
                value={fmt(calc.tax)}
              />

              <tr style={{ background: '#eff6ff' }}>
                <td style={{ ...tdBold, textAlign: 'center' }} />
                <td style={tdBold}>ИТОГО для Заказчика</td>
                <td style={tdBoldRight} />
                <td style={{ ...tdBoldRight, fontSize: '15px', color: '#2563eb' }}>
                  {fmt(calc.total_for_customer)}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Right table: Section breakdown ── */}
      {calc.section_totals.length > 0 && (
        <div style={{ flex: '1 1 560px', minWidth: 0 }}>
          <div style={{
            fontSize: '12px', fontWeight: 700, color: '#7c3aed',
            textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '8px',
          }}>
            Разбивка по разделам
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  <th style={thStyle}>Раздел</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Работы (с/с)</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>НДС {pct(overrides.vat_works_pct)}</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Работы с НДС</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Материалы (с/с)</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>НДС {pct(overrides.vat_materials_pct)}</th>
                  <th style={{ ...thStyle, textAlign: 'right' }}>Материалы с НДС</th>
                </tr>
              </thead>
              <tbody>
                {calc.section_totals.map((sec) => (
                  <tr key={sec.card_id}>
                    <td style={tdStyle}>{sec.card_name}</td>
                    <td style={tdRight}>{fmt(sec.works)}</td>
                    <td style={tdRight}>{fmt(sec.vat_works)}</td>
                    <td style={tdRight}>{fmt(sec.works_with_vat)}</td>
                    <td style={tdRight}>{fmt(sec.materials)}</td>
                    <td style={tdRight}>{fmt(sec.vat_materials)}</td>
                    <td style={tdRight}>{fmt(sec.materials_with_vat)}</td>
                  </tr>
                ))}
                <tr style={{ background: '#f8fafc' }}>
                  <td style={tdBold}>ИТОГО</td>
                  <td style={tdBoldRight}>{fmt(calc.works)}</td>
                  <td style={tdBoldRight}>
                    {fmt((calc.works * overrides.vat_works_pct) / 100)}
                  </td>
                  <td style={tdBoldRight}>
                    {fmt(calc.works + (calc.works * overrides.vat_works_pct) / 100)}
                  </td>
                  <td style={tdBoldRight}>{fmt(calc.materials)}</td>
                  <td style={tdBoldRight}>
                    {fmt((calc.materials * overrides.vat_materials_pct) / 100)}
                  </td>
                  <td style={tdBoldRight}>
                    {fmt(calc.materials + (calc.materials * overrides.vat_materials_pct) / 100)}
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

function Row({
  num,
  label,
  editCell,
  value,
}: {
  num?: number
  label: string
  editCell?: React.ReactNode
  value: string
}) {
  return (
    <tr>
      <td style={{ ...tdStyle, textAlign: 'center', color: '#94a3b8', fontSize: '12px' }}>
        {num ?? ''}
      </td>
      <td style={tdStyle}>{label}</td>
      <td style={tdRight}>{editCell ?? null}</td>
      <td style={tdRight}>{value}</td>
    </tr>
  )
}

function TotalRow({ label, value }: { label: string; value: string }) {
  return (
    <tr style={{ background: '#f1f5f9' }}>
      <td style={{ ...tdBold, textAlign: 'center', color: '#94a3b8' }} />
      <td style={tdBold}>{label}</td>
      <td style={tdBoldRight} />
      <td style={tdBoldRight}>{value}</td>
    </tr>
  )
}

export default SummarySheet
