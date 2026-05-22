import React, { useEffect, useState } from 'react'
import { WorkflowCard } from '../../types/workflow'
import { EstimateVersionSummary } from '../../types'
import { getVersions, initEstimateVersionFromResult } from '../../api/estimateVersions'
import { SectionInput } from '../../types/summary'
import { LumaSpin } from '../ui/LumaSpin'

interface Props {
  cards: WorkflowCard[]
  onConfirm: (sections: SectionInput[]) => Promise<void>
  onClose: () => void
}

type VersionMap = Record<string, EstimateVersionSummary[]>

const VERSION_TYPES: { key: string; label: string }[] = [
  { key: 'original', label: 'Смета из перечня' },
  { key: 'completeness_checked', label: 'V1 — Полнота' },
  { key: 'no_redundant', label: 'V2 — Лишнее' },
  { key: 'tech_optimized', label: 'V3 — Технологии' },
  { key: 'material_optimized', label: 'V4 — Материалы' },
  { key: 'prices_filled', label: 'V5 — Цены' },
]

function versionLabel(v: EstimateVersionSummary): string {
  return VERSION_TYPES.find((vt) => vt.key === v.version_label)?.label ?? v.version_display_name
}

const SectionSelector: React.FC<Props> = ({ cards, onConfirm, onClose }) => {
  const eligibleCards = cards.filter(
    (c) => c.estimate_task_id || c.optimization_task_id,
  )

  // which cards are included
  const [checked, setChecked] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    eligibleCards.forEach((c) => { init[c.id] = true })
    return init
  })
  // one selected version per card
  const [selectedVersionIds, setSelectedVersionIds] = useState<Record<string, string>>({})
  const [versionMap, setVersionMap] = useState<VersionMap>({})
  const [loadingVersions, setLoadingVersions] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    async function loadAll() {
      setLoadingVersions(true)
      const map: VersionMap = {}
      const initSel: Record<string, string> = {}

      await Promise.all(
        eligibleCards.map(async (card) => {
          const allVersions: EstimateVersionSummary[] = []

          // original (V0) from estimate task
          if (card.estimate_task_id) {
            try {
              let versions = await getVersions(card.estimate_task_id)
              if (versions.length === 0) {
                try {
                  await initEstimateVersionFromResult(card.estimate_task_id)
                  versions = await getVersions(card.estimate_task_id)
                } catch { /* task not completed */ }
              }
              allVersions.push(...versions.filter((v) => !v.is_rolled_back))
            } catch { /* ignore */ }
          }

          // V1–V5 from optimization task
          if (card.optimization_task_id) {
            try {
              const versions = await getVersions(card.optimization_task_id)
              allVersions.push(...versions.filter((v) => !v.is_rolled_back))
            } catch { /* ignore */ }
          }

          // deduplicate by version_label — keep highest version_number
          const byLabel = new Map<string, EstimateVersionSummary>()
          for (const v of allVersions) {
            const existing = byLabel.get(v.version_label)
            if (!existing || v.version_number > existing.version_number) {
              byLabel.set(v.version_label, v)
            }
          }

          // order by VERSION_TYPES, unknowns at the end
          const ordered: EstimateVersionSummary[] = []
          for (const vt of VERSION_TYPES) {
            const found = byLabel.get(vt.key)
            if (found) ordered.push(found)
          }
          for (const v of byLabel.values()) {
            if (!VERSION_TYPES.find((vt) => vt.key === v.version_label)) ordered.push(v)
          }

          map[card.id] = ordered

          // pre-select: primary_version_id, else the last available version
          if (ordered.length > 0) {
            const preselect =
              (card.primary_version_id && ordered.find((v) => v.id === card.primary_version_id))
              || ordered[ordered.length - 1]
            initSel[card.id] = preselect.id
          }
        }),
      )

      setVersionMap(map)
      setSelectedVersionIds(initSel)
      setLoadingVersions(false)
    }
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleToggleCard = (cardId: string) => {
    setChecked((prev) => ({ ...prev, [cardId]: !prev[cardId] }))
  }

  const handleVersionSelect = (cardId: string, versionId: string) => {
    setSelectedVersionIds((prev) => ({ ...prev, [cardId]: versionId }))
  }

  const handleConfirm = async () => {
    setError('')
    const sections: SectionInput[] = eligibleCards
      .filter((c) => checked[c.id] && selectedVersionIds[c.id])
      .map((c) => ({ card_id: c.id, version_id: selectedVersionIds[c.id] }))

    if (sections.length === 0) {
      setError('Выберите хотя бы один раздел')
      return
    }
    setCreating(true)
    try {
      await onConfirm(sections)
    } catch {
      setError('Не удалось создать сводную. Попробуйте ещё раз.')
    } finally {
      setCreating(false)
    }
  }

  return (
    <div
      style={{
        position: 'fixed', inset: 0, zIndex: 1000,
        background: 'rgba(15,23,42,0.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: '#fff',
          borderRadius: '16px',
          padding: '28px',
          width: '560px',
          maxWidth: '95vw',
          maxHeight: '82vh',
          overflowY: 'auto',
          boxShadow: '0 8px 40px rgba(0,0,0,0.18)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ margin: '0 0 6px', fontSize: '18px', fontWeight: 700, color: '#0f172a' }}>
          Создать сводную себестоимость
        </h2>
        <p style={{ margin: '0 0 20px', fontSize: '13px', color: '#64748b' }}>
          Выберите разделы и версию сметы для каждого.
        </p>

        {loadingVersions ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '32px 0' }}>
            <LumaSpin size="md" color="#3b82f6" />
          </div>
        ) : eligibleCards.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '24px 0', color: '#94a3b8', fontSize: '14px' }}>
            Нет карточек со сметами. Создайте расчёты в разделах проекта.
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {eligibleCards.map((card) => {
              const versions = versionMap[card.id] ?? []
              const isChecked = checked[card.id]

              return (
                <div
                  key={card.id}
                  style={{
                    border: isChecked ? '1.5px solid #93c5fd' : '1px solid #e2e8f0',
                    borderRadius: '10px',
                    overflow: 'hidden',
                    background: isChecked ? '#f0f9ff' : '#fafafa',
                    transition: 'all 0.15s',
                  }}
                >
                  {/* Card header with include checkbox */}
                  <label style={{
                    display: 'flex', alignItems: 'center', gap: '10px',
                    padding: '11px 14px',
                    cursor: 'pointer',
                    borderBottom: versions.length > 0 && isChecked ? '1px solid #e0f2fe' : 'none',
                  }}>
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => handleToggleCard(card.id)}
                      style={{ width: 15, height: 15, accentColor: '#3b82f6', cursor: 'pointer', flexShrink: 0 }}
                    />
                    <span style={{ fontWeight: 600, fontSize: '14px', color: isChecked ? '#1e293b' : '#94a3b8' }}>
                      {card.name}
                    </span>
                  </label>

                  {/* Version radio buttons — only visible when card is checked */}
                  {isChecked && versions.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', padding: '10px 14px' }}>
                      {versions.map((v) => {
                        const isSelected = selectedVersionIds[card.id] === v.id
                        return (
                          <label
                            key={v.id}
                            style={{
                              display: 'flex', alignItems: 'center', gap: '6px',
                              padding: '5px 11px',
                              borderRadius: '20px',
                              border: isSelected ? '1.5px solid #3b82f6' : '1px solid #e2e8f0',
                              background: isSelected ? '#eff6ff' : '#fff',
                              cursor: 'pointer',
                              fontSize: '13px',
                              color: isSelected ? '#1d4ed8' : '#475569',
                              fontWeight: isSelected ? 600 : 400,
                              transition: 'all 0.13s',
                              userSelect: 'none',
                            }}
                          >
                            <input
                              type="radio"
                              name={`version-${card.id}`}
                              value={v.id}
                              checked={isSelected}
                              onChange={() => handleVersionSelect(card.id, v.id)}
                              style={{ display: 'none' }}
                            />
                            {versionLabel(v)}
                          </label>
                        )
                      })}
                    </div>
                  )}

                  {isChecked && versions.length === 0 && (
                    <div style={{ padding: '10px 14px', fontSize: '12px', color: '#94a3b8' }}>
                      Нет доступных версий
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {error && (
          <div style={{ marginTop: '12px', fontSize: '13px', color: '#dc2626' }}>{error}</div>
        )}

        <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end', marginTop: '24px' }}>
          <button
            onClick={onClose}
            style={{
              padding: '8px 20px', fontSize: '13px', borderRadius: '8px',
              border: '1px solid #e2e8f0', background: '#fff', color: '#475569', cursor: 'pointer',
            }}
          >
            Отмена
          </button>
          <button
            onClick={handleConfirm}
            disabled={creating || loadingVersions}
            style={{
              padding: '8px 20px', fontSize: '13px', fontWeight: 600, borderRadius: '8px',
              border: 'none',
              background: creating || loadingVersions ? '#93c5fd' : '#3b82f6',
              color: '#fff',
              cursor: creating || loadingVersions ? 'not-allowed' : 'pointer',
              display: 'flex', alignItems: 'center', gap: '8px',
            }}
          >
            {creating && <LumaSpin size="sm" color="#fff" />}
            Создать сводную
          </button>
        </div>
      </div>
    </div>
  )
}

export default SectionSelector
