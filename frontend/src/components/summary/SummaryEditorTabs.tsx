import React, { useState } from 'react'
import { Download, Save, Table2 } from 'lucide-react'
import EstimateGrid from '../estimate/EstimateGrid'
import SummarySheet from './SummarySheet'
import CustomExportModal from './CustomExportModal'
import { useSummaryEditorStore, calcSummary } from '../../stores/summaryEditorStore'
import { exportSummary } from '../../api/summaryEstimate'
import { EstimateRow } from '../../types'
import { LumaSpin } from '../ui/LumaSpin'

interface Props {
  projectId: string
  projectName?: string
}

type GridTabState = 'all' | 'works' | 'materials'

// -1 means the «Сводная» sheet is active
const SUMMARY_IDX = -1

const SummaryEditorTabs: React.FC<Props> = ({ projectId, projectName }) => {
  const {
    sections,
    summaryOverrides,
    activeTabIndex,
    isDirty,
    undoStack,
    redoStack,
    setActiveTabIndex,
    updateSectionRows,
    updateSectionTaxPct,
    updateOverride,
    save,
    undo,
    redo,
  } = useSummaryEditorStore()

  const [saving, setSaving] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [saveError, setSaveError] = useState('')
  const [showCustomExport, setShowCustomExport] = useState(false)

  const [gridTabs, setGridTabs] = useState<GridTabState[]>(() =>
    sections.map(() => 'all' as GridTabState),
  )
  const [selectedRowIds, setSelectedRowIds] = useState<ReadonlySet<string>[]>(() =>
    sections.map(() => new Set<string>()),
  )

  const isSummaryActive = activeTabIndex === SUMMARY_IDX

  const handleSave = async () => {
    setSaving(true)
    setSaveError('')
    try {
      await save()
    } catch {
      setSaveError('Не удалось сохранить')
    } finally {
      setSaving(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      await exportSummary(projectId, projectName)
    } catch {
      // silent
    } finally {
      setExporting(false)
    }
  }

  const calc = calcSummary(sections, summaryOverrides)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* ── Toolbar ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 0 12px', flexWrap: 'wrap' }}>
        <button
          onClick={handleSave}
          disabled={saving || !isDirty}
          title={!isDirty ? 'Нет несохранённых изменений' : undefined}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            padding: '7px 14px', fontSize: '13px', fontWeight: 600,
            borderRadius: '8px', border: 'none',
            background: isDirty ? '#3b82f6' : '#e2e8f0',
            color: isDirty ? '#fff' : '#94a3b8',
            cursor: isDirty && !saving ? 'pointer' : 'not-allowed',
            transition: 'all 0.15s',
          }}
        >
          {saving ? <LumaSpin size="sm" color="#fff" /> : <Save size={14} />}
          Сохранить
        </button>

        <button
          onClick={handleExport}
          disabled={exporting}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            padding: '7px 14px', fontSize: '13px', fontWeight: 500,
            borderRadius: '8px', border: '1px solid #e2e8f0',
            background: '#fff', color: '#374151',
            cursor: exporting ? 'not-allowed' : 'pointer',
          }}
        >
          {exporting ? <LumaSpin size="sm" color="#64748b" /> : <Download size={14} />}
          Экспорт xlsx
        </button>

        <button
          onClick={() => setShowCustomExport(true)}
          style={{
            display: 'flex', alignItems: 'center', gap: '6px',
            padding: '7px 14px', fontSize: '13px', fontWeight: 500,
            borderRadius: '8px', border: '1px solid #e2e8f0',
            background: '#fff', color: '#374151', cursor: 'pointer',
          }}
        >
          <Table2 size={14} />
          Сформировать выгрузку
        </button>

        {saveError && <span style={{ fontSize: '12px', color: '#dc2626' }}>{saveError}</span>}
        {isDirty && (
          <span style={{ fontSize: '12px', color: '#f59e0b', marginLeft: 'auto' }}>
            Есть несохранённые изменения
          </span>
        )}
      </div>

      {/* ── Tabs ── */}
      <div style={{
        display: 'flex', gap: '4px', marginBottom: '16px',
        overflowX: 'auto', paddingBottom: '2px', flexWrap: 'nowrap', alignItems: 'center',
      }}>
        {sections.map((sec, idx) => {
          const isActive = activeTabIndex === idx && !isSummaryActive
          return (
            <button
              key={sec.card_id}
              onClick={() => setActiveTabIndex(idx)}
              style={{
                padding: '6px 14px', fontSize: '13px',
                fontWeight: isActive ? 600 : 400, borderRadius: '6px',
                border: isActive ? '2px solid #2563eb' : '1px solid #e2e8f0',
                background: isActive ? '#eff6ff' : '#fff',
                color: isActive ? '#2563eb' : '#374151',
                cursor: 'pointer', whiteSpace: 'nowrap',
                maxWidth: '180px', overflow: 'hidden', textOverflow: 'ellipsis',
                transition: 'all 0.1s',
              }}
              title={sec.card_name}
            >
              {sec.card_name}
            </button>
          )
        })}

        {sections.length > 0 && (
          <div style={{ width: '1px', height: '24px', background: '#e2e8f0', margin: '0 4px', flexShrink: 0 }} />
        )}

        <button
          onClick={() => setActiveTabIndex(SUMMARY_IDX)}
          style={{
            padding: '6px 14px', fontSize: '13px',
            fontWeight: isSummaryActive ? 600 : 400, borderRadius: '6px',
            border: isSummaryActive ? '2px solid #7c3aed' : '1px solid #e2e8f0',
            background: isSummaryActive ? '#f5f3ff' : '#fff',
            color: isSummaryActive ? '#7c3aed' : '#374151',
            cursor: 'pointer', whiteSpace: 'nowrap', flexShrink: 0,
          }}
        >
          Сводная
        </button>
      </div>

      {/* ── Content ── */}
      <div style={{ flex: 1, minHeight: 0 }}>
        {isSummaryActive ? (
          <SummarySheet
            calc={calc}
            overrides={summaryOverrides}
            onUpdateOverride={updateOverride}
            onUpdateSectionTaxPct={updateSectionTaxPct}
          />
        ) : (
          sections.map((sec, idx) => (
            <div
              key={sec.card_id}
              style={{ display: activeTabIndex === idx ? 'block' : 'none', height: '100%' }}
            >
              <EstimateGrid
                rows={sec.rows}
                selectedRowIds={selectedRowIds[idx] ?? new Set()}
                activeTab={gridTabs[idx] ?? 'all'}
                canUndo={activeTabIndex === idx && undoStack.length > 0}
                canRedo={activeTabIndex === idx && redoStack.length > 0}
                onRowsChange={(rows: EstimateRow[]) => updateSectionRows(idx, rows)}
                onSelectedRowIdsChange={(ids) => setSelectedRowIds((prev) => {
                  const next = [...prev]; next[idx] = ids; return next
                })}
                onTabChange={(tab) => setGridTabs((prev) => {
                  const next = [...prev]; next[idx] = tab; return next
                })}
                onSave={handleSave}
                onUndo={activeTabIndex === idx ? undo : undefined}
                onRedo={activeTabIndex === idx ? redo : undefined}
              />
            </div>
          ))
        )}
      </div>

      {showCustomExport && (
        <CustomExportModal
          projectId={projectId}
          projectName={projectName}
          sections={sections}
          onClose={() => setShowCustomExport(false)}
        />
      )}
    </div>
  )
}

export default SummaryEditorTabs
