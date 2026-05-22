import React from 'react'
import { SummaryOverrides, SummaryCalcResult } from '../../types/summary'

interface Props {
  calc: SummaryCalcResult
  overrides: SummaryOverrides
  onUpdateOverride: <K extends keyof SummaryOverrides>(key: K, value: number) => void
  onUpdateSectionTaxPct: (sectionIndex: number, taxPct: number) => void
}

const fmt = (n: number) =>
  n === 0 ? '—' : Math.round(n).toLocaleString('ru-RU') + ' ₽'

const fmtVal = (n: number) =>
  Math.round(n).toLocaleString('ru-RU') + ' ₽'

// ── NumberInput ──────────────────────────────────────────────────────────────

interface NumberInputProps {
  value: number
  onCommit: (v: number) => void
  suffix?: string
  min?: number
  placeholder?: string
}

function NumberInput({ value, onCommit, suffix = '', min = 0, placeholder }: NumberInputProps) {
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
          width: '90px', padding: '2px 6px', fontSize: '13px',
          border: '1.5px solid #3b82f6', borderRadius: '4px',
          outline: 'none', textAlign: 'right',
        }}
      />
    )
  }

  const display = value === 0 && placeholder ? placeholder : `${value}${suffix}`
  return (
    <span
      onClick={() => setEditing(true)}
      title="Нажмите для редактирования"
      style={{
        cursor: 'pointer', padding: '2px 6px', borderRadius: '4px',
        border: '1px dashed #cbd5e1', fontSize: '13px',
        color: value === 0 ? '#94a3b8' : '#1e293b',
        userSelect: 'none', display: 'inline-block',
        minWidth: '60px', textAlign: 'right',
      }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#93c5fd' }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#cbd5e1' }}
    >
      {display}
    </span>
  )
}

// ── Styles ───────────────────────────────────────────────────────────────────

const thStyle: React.CSSProperties = {
  padding: '8px 8px', fontSize: '11px', fontWeight: 700,
  color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.04em',
  textAlign: 'left', borderBottom: '2px solid #e2e8f0',
  whiteSpace: 'nowrap', background: '#f8fafc',
}
const th = (extra?: React.CSSProperties): React.CSSProperties => ({ ...thStyle, ...extra })

const tdBase: React.CSSProperties = {
  padding: '6px 8px', fontSize: '13px', color: '#374151',
  borderBottom: '1px solid #f1f5f9', verticalAlign: 'middle',
}
const td = (extra?: React.CSSProperties): React.CSSProperties => ({ ...tdBase, ...extra })
const tdR = (extra?: React.CSSProperties): React.CSSProperties => ({ ...tdBase, textAlign: 'right', ...extra })

const tdBoldBase: React.CSSProperties = {
  ...tdBase, fontWeight: 700, color: '#0f172a', background: '#f8fafc',
}
const tdB = (extra?: React.CSSProperties): React.CSSProperties => ({ ...tdBoldBase, ...extra })
const tdBR = (extra?: React.CSSProperties): React.CSSProperties => ({ ...tdBoldBase, textAlign: 'right', ...extra })

// ── Main component ────────────────────────────────────────────────────────────

const SummarySheet: React.FC<Props> = ({ calc, overrides, onUpdateOverride, onUpdateSectionTaxPct }) => {
  return (
    <div style={{ display: 'flex', gap: '24px', flexWrap: 'wrap' }}>

      {/* ── Left table ─────────────────────────────────────────────────────── */}
      <div style={{ flex: '1 1 620px', minWidth: 0 }}>
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
            </colgroup>
            <thead>
              <tr>
                <th style={th({ textAlign: 'center' })}>№</th>
                <th style={th()}>Наименование</th>
                <th style={th({ textAlign: 'center' })}>%&nbsp;/&nbsp;Кол-во</th>
                <th style={th({ textAlign: 'right' })}>Стоимость с НДС</th>
                <th style={th({ textAlign: 'right' })}>Стоимость без НДС</th>
              </tr>
            </thead>
            <tbody>

              {/* Коэффициент */}
              <tr style={{ background: '#faf5ff' }}>
                <td style={td({ textAlign: 'center' })} />
                <td style={td({ fontWeight: 600, color: '#7c3aed' })}>
                  Коэффициент к ценам
                  <span style={{ marginLeft: 6, fontSize: '11px', fontWeight: 400, color: '#9ca3af' }}>(×все цены)</span>
                </td>
                <td style={tdR()}>
                  <NumberInput value={overrides.coefficient} onCommit={(v) => onUpdateOverride('coefficient', v)} min={0.01} />
                </td>
                <td style={tdR()} />
                <td style={tdR()} />
              </tr>

              {/* Row 1: Работы */}
              <Row num={1} label="Работы"
                withVat={fmtVal(calc.works_with_vat)}
                withoutVat={fmtVal(calc.works_without_vat)}
              />

              {/* Row 2: Материалы */}
              <Row num={2} label="Материалы"
                withVat={fmtVal(calc.materials_with_vat)}
                withoutVat={fmtVal(calc.materials_without_vat)}
              />

              {/* Row 3: Транспортные */}
              <Row num={3} label="Транспортные расходы"
                editCell={
                  <NumberInput value={overrides.transport_pct} onCommit={(v) => onUpdateOverride('transport_pct', v)} suffix="%" />
                }
                withVat={fmt(calc.transport_with_vat)}
                withoutVat={fmt(calc.transport_without_vat)}
              />

              {/* Row 4: Уборка */}
              <Row num={4} label="Уборка и вывоз мусора"
                editCell={
                  <NumberInput value={overrides.cleanup_pct} onCommit={(v) => onUpdateOverride('cleanup_pct', v)} suffix="%" />
                }
                withVat={fmt(calc.cleanup_with_vat)}
                withoutVat={fmt(calc.cleanup_without_vat)}
              />

              {/* Row 5: Накладные */}
              <Row num={5} label="Накладные"
                editCell={
                  <NumberInput value={overrides.overhead_pct} onCommit={(v) => onUpdateOverride('overhead_pct', v)} suffix="%" />
                }
                withVat={fmt(calc.overhead_with_vat)}
                withoutVat={fmt(calc.overhead_without_vat)}
              />

              {/* Row 6: Разнорабочие ежедневно */}
              <Row num={6} label="Разнорабочие ежедневно"
                editCell={
                  <NumberInput value={overrides.daily_workers_cost} onCommit={(v) => onUpdateOverride('daily_workers_cost', v)} suffix=" чел" />
                }
                withVat={fmt(calc.daily_workers_with_vat)}
                withoutVat={fmt(calc.daily_workers_without_vat)}
              />

              {/* Rows 7–18: ручные */}
              <ManualRow num={7} label="Банковская гарантия"
                withoutVat={overrides.bank_guarantee_cost}
                withVat={calc.bank_guarantee_with_vat}
                onChangeWithout={(v) => onUpdateOverride('bank_guarantee_cost', v)}
                onChangeWith={(v) => onUpdateOverride('bank_guarantee_cost', v / 1.22)}
              />
              <ManualRow num={8} label="Клининг"
                withoutVat={overrides.cleaning_cost}
                withVat={calc.cleaning_with_vat}
                onChangeWithout={(v) => onUpdateOverride('cleaning_cost', v)}
                onChangeWith={(v) => onUpdateOverride('cleaning_cost', v / 1.22)}
              />
              <ManualRow num={9} label="Рабочая документация (ППР)"
                withoutVat={overrides.ppr_cost}
                withVat={calc.ppr_with_vat}
                onChangeWithout={(v) => onUpdateOverride('ppr_cost', v)}
                onChangeWith={(v) => onUpdateOverride('ppr_cost', v / 1.22)}
              />
              <ManualRow num={10} label="Разнорабочие мусор"
                withoutVat={overrides.commissioning_cost}
                withVat={calc.commissioning_with_vat}
                onChangeWithout={(v) => onUpdateOverride('commissioning_cost', v)}
                onChangeWith={(v) => onUpdateOverride('commissioning_cost', v / 1.22)}
              />
              <ManualRow num={11} label="Строительный контроль"
                withoutVat={overrides.construction_control_cost}
                withVat={calc.construction_control_with_vat}
                onChangeWithout={(v) => onUpdateOverride('construction_control_cost', v)}
                onChangeWith={(v) => onUpdateOverride('construction_control_cost', v / 1.22)}
              />
              <ManualRow num={12} label="Авторский надзор"
                withoutVat={overrides.author_supervision_cost}
                withVat={calc.author_supervision_with_vat}
                onChangeWithout={(v) => onUpdateOverride('author_supervision_cost', v)}
                onChangeWith={(v) => onUpdateOverride('author_supervision_cost', v / 1.22)}
              />
              <ManualRow num={13} label="Пропуски, корочки"
                withoutVat={overrides.passes_cost}
                withVat={calc.passes_with_vat}
                onChangeWithout={(v) => onUpdateOverride('passes_cost', v)}
                onChangeWith={(v) => onUpdateOverride('passes_cost', v / 1.22)}
              />
              <ManualRow num={14} label="Бытовка"
                withoutVat={overrides.site_office_cost}
                withVat={calc.site_office_with_vat}
                onChangeWithout={(v) => onUpdateOverride('site_office_cost', v)}
                onChangeWith={(v) => onUpdateOverride('site_office_cost', v / 1.22)}
              />
              <ManualRow num={15} label="Командировочные"
                withoutVat={overrides.travel_cost}
                withVat={calc.travel_with_vat}
                onChangeWithout={(v) => onUpdateOverride('travel_cost', v)}
                onChangeWith={(v) => onUpdateOverride('travel_cost', v / 1.22)}
              />
              <ManualRow num={16} label="РП"
                withoutVat={overrides.rp_cost}
                withVat={calc.rp_with_vat}
                onChangeWithout={(v) => onUpdateOverride('rp_cost', v)}
                onChangeWith={(v) => onUpdateOverride('rp_cost', v / 1.22)}
              />
              <ManualRow num={17} label="Аренда жилья"
                withoutVat={overrides.housing_rent_cost}
                withVat={calc.housing_rent_with_vat}
                onChangeWithout={(v) => onUpdateOverride('housing_rent_cost', v)}
                onChangeWith={(v) => onUpdateOverride('housing_rent_cost', v / 1.22)}
              />
              <ManualRow num={18} label="Транспортные расходы люди"
                withoutVat={overrides.workers_transport_cost}
                withVat={calc.workers_transport_with_vat}
                onChangeWithout={(v) => onUpdateOverride('workers_transport_cost', v)}
                onChangeWith={(v) => onUpdateOverride('workers_transport_cost', v / 1.22)}
              />

              {/* Разделитель */}
              <tr><td colSpan={5} style={{ height: '4px', background: '#e2e8f0', padding: 0 }} /></tr>

              {/* Сумма по наименованиям = ИТОГО себестоимость объекта */}
              <tr style={{ background: '#f1f5f9' }}>
                <td style={tdB({ textAlign: 'center', color: '#94a3b8' })} />
                <td style={tdB()}>ИТОГО себестоимость объекта</td>
                <td style={tdBR()} />
                <td style={tdBR()}>{fmtVal(calc.subtotal_with_vat)}</td>
                <td style={tdBR()}>{fmtVal(calc.subtotal_without_vat)}</td>
              </tr>

              {/* Непредвиденные расходы */}
              <Row label="Непредвиденные расходы"
                editCell={
                  <NumberInput value={overrides.contingency_pct} onCommit={(v) => onUpdateOverride('contingency_pct', v)} suffix="%" />
                }
                withVat={fmt(calc.contingency_with_vat)}
                withoutVat={fmt(calc.contingency_without_vat)}
              />

              {/* Плановая прибыль — merged cell */}
              <tr>
                <td style={td({ textAlign: 'center', color: '#94a3b8' })} />
                <td style={td()}>Плановая прибыль (без НДС)</td>
                <td style={tdR()}>
                  <NumberInput value={overrides.profit_pct} onCommit={(v) => onUpdateOverride('profit_pct', v)} suffix="%" />
                </td>
                <td style={tdR({ color: '#059669', fontWeight: 600 })} colSpan={2}>
                  {fmtVal(calc.profit)}
                </td>
              </tr>

              {/* Полная себестоимость — merged */}
              <tr style={{ background: '#f1f5f9' }}>
                <td style={tdB({ textAlign: 'center', color: '#94a3b8' })} />
                <td style={tdB()}>Полная себестоимость с учётом прибыли и непредвиденных (без НДС)</td>
                <td style={tdBR()} />
                <td style={tdBR({ fontSize: '14px' })} colSpan={2}>
                  {fmtVal(calc.full_cost_without_vat)}
                </td>
              </tr>

              {/* НДС от полной себестоимости — merged */}
              <Row label="НДС от полной себестоимости"
                editCell={
                  <NumberInput value={overrides.vat_full_cost_pct} onCommit={(v) => onUpdateOverride('vat_full_cost_pct', v)} suffix="%" />
                }
                merged
                mergedValue={fmt(calc.vat)}
              />

              {/* Др. налоги — merged */}
              <Row label="Др. налоги от полной себестоимости"
                editCell={
                  <NumberInput value={overrides.tax_pct} onCommit={(v) => onUpdateOverride('tax_pct', v)} suffix="%" />
                }
                merged
                mergedValue={fmt(calc.other_tax)}
              />

              {/* ИТОГО для Заказчика — merged, bold blue */}
              <tr style={{ background: '#eff6ff' }}>
                <td style={tdB({ textAlign: 'center' })} />
                <td style={tdB({ fontSize: '14px', color: '#2563eb' })}>
                  ИТОГО по смете для Заказчика с учётом налогов
                </td>
                <td style={tdBR()} />
                <td style={{ ...tdBR({ fontSize: '16px', color: '#2563eb' }) }} colSpan={2}>
                  {fmtVal(calc.total_for_customer)}
                </td>
              </tr>

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
            Налог: 0% — подрядчик с НДС (добавляем 22%); 22% — самозанятый (НДС уже в цене, ничего не добавляем)
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <colgroup>
                <col />
                <col style={{ width: '130px' }} />
                <col style={{ width: '72px' }} />
                <col style={{ width: '130px' }} />
                <col style={{ width: '4px' }} />
                <col style={{ width: '130px' }} />
                <col style={{ width: '72px' }} />
                <col style={{ width: '130px' }} />
              </colgroup>
              <thead>
                <tr>
                  <th style={th()}>Раздел</th>
                  <th style={th({ textAlign: 'right' })}>Работы из сметы (с/с)</th>
                  <th style={th({ textAlign: 'center' })}>Налог %</th>
                  <th style={th({ textAlign: 'right' })}>Стоимость работ с НДС</th>
                  {/* vertical divider */}
                  <th style={{ ...thStyle, padding: 0, borderLeft: '2px solid #e2e8f0', background: '#e2e8f0' }} />
                  <th style={th({ textAlign: 'right', borderLeft: '2px solid #e2e8f0' })}>Материалы из сметы (с/с)</th>
                  <th style={th({ textAlign: 'center' })}>Налог %</th>
                  <th style={th({ textAlign: 'right' })}>Стоимость матер. с НДС</th>
                </tr>
              </thead>
              <tbody>
                {calc.section_totals.map((sec, idx) => (
                  <tr key={sec.card_id}>
                    <td style={td()}>{sec.card_name}</td>
                    <td style={tdR()}>{fmt(sec.works_raw)}</td>
                    <td style={td({ textAlign: 'center' })}>
                      <NumberInput
                        value={sec.tax_pct}
                        onCommit={(v) => onUpdateSectionTaxPct(idx, v)}
                        suffix="%"
                      />
                    </td>
                    <td style={tdR({ color: sec.tax_pct > 0 ? '#059669' : undefined })}>
                      {fmtVal(sec.works_with_vat)}
                    </td>
                    <td style={{ padding: 0, borderLeft: '2px solid #e2e8f0', background: '#e2e8f0', borderBottom: '1px solid #f1f5f9' }} />
                    <td style={tdR({ borderLeft: '2px solid #e2e8f0' })}>{fmt(sec.materials_raw)}</td>
                    <td style={td({ textAlign: 'center' })}>
                      <NumberInput
                        value={sec.tax_pct}
                        onCommit={(v) => onUpdateSectionTaxPct(idx, v)}
                        suffix="%"
                      />
                    </td>
                    <td style={tdR({ color: sec.tax_pct > 0 ? '#059669' : undefined })}>
                      {fmtVal(sec.materials_with_vat)}
                    </td>
                  </tr>
                ))}

                {/* ИТОГО */}
                <tr style={{ background: '#f8fafc' }}>
                  <td style={tdB()}>ИТОГО</td>
                  <td style={tdBR()}>
                    {fmtVal(calc.section_totals.reduce((s, r) => s + r.works_raw, 0))}
                  </td>
                  <td style={tdB()} />
                  <td style={tdBR()}>{fmtVal(calc.works_with_vat)}</td>
                  <td style={{ padding: 0, borderLeft: '2px solid #e2e8f0', background: '#e2e8f0' }} />
                  <td style={tdBR({ borderLeft: '2px solid #e2e8f0' })}>
                    {fmtVal(calc.section_totals.reduce((s, r) => s + r.materials_raw, 0))}
                  </td>
                  <td style={tdB()} />
                  <td style={tdBR()}>{fmtVal(calc.materials_with_vat)}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Helper rows ──────────────────────────────────────────────────────────────

function Row({
  num,
  label,
  editCell,
  withVat,
  withoutVat,
  merged,
  mergedValue,
}: {
  num?: number
  label: string
  editCell?: React.ReactNode
  withVat?: string
  withoutVat?: string
  merged?: boolean
  mergedValue?: string
}) {
  const tdBase2: React.CSSProperties = {
    padding: '6px 8px', fontSize: '13px', color: '#374151',
    borderBottom: '1px solid #f1f5f9', verticalAlign: 'middle',
  }
  return (
    <tr>
      <td style={{ ...tdBase2, textAlign: 'center', color: '#94a3b8', fontSize: '12px' }}>
        {num ?? ''}
      </td>
      <td style={tdBase2}>{label}</td>
      <td style={{ ...tdBase2, textAlign: 'right' }}>{editCell ?? null}</td>
      {merged ? (
        <td style={{ ...tdBase2, textAlign: 'right' }} colSpan={2}>{mergedValue}</td>
      ) : (
        <>
          <td style={{ ...tdBase2, textAlign: 'right' }}>{withVat}</td>
          <td style={{ ...tdBase2, textAlign: 'right', color: '#64748b' }}>{withoutVat}</td>
        </>
      )}
    </tr>
  )
}

function ManualRow({
  num,
  label,
  withoutVat,
  withVat,
  onChangeWithout,
  onChangeWith,
}: {
  num: number
  label: string
  withoutVat: number
  withVat: number
  onChangeWithout: (v: number) => void
  onChangeWith: (v: number) => void
}) {
  const tdBase2: React.CSSProperties = {
    padding: '6px 8px', fontSize: '13px', color: '#374151',
    borderBottom: '1px solid #f1f5f9', verticalAlign: 'middle',
  }
  return (
    <tr>
      <td style={{ ...tdBase2, textAlign: 'center', color: '#94a3b8', fontSize: '12px' }}>
        {num}
      </td>
      <td style={tdBase2}>{label}</td>
      <td style={{ ...tdBase2, textAlign: 'right' }} />
      <td style={{ ...tdBase2, textAlign: 'right' }}>
        <NumberInput
          value={Math.round(withVat)}
          onCommit={onChangeWith}
          suffix=" ₽"
          placeholder="0 ₽"
        />
      </td>
      <td style={{ ...tdBase2, textAlign: 'right', color: '#64748b' }}>
        <NumberInput
          value={Math.round(withoutVat)}
          onCommit={onChangeWithout}
          suffix=" ₽"
          placeholder="0 ₽"
        />
      </td>
    </tr>
  )
}

export default SummarySheet
