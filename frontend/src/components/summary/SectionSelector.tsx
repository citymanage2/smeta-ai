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

const selKey = (cardId: string, versionId: string) => `${cardId}__${versionId}`

const SectionSelector: React.FC<Props> = ({ cards, onConfirm, onClose }) => {
  const eligibleCards = cards.filter(
    (c) => c.estimate_task_id || c.optimization_task_id,
  )

  const [selectedItems, setSelectedItems] = useState<Record<string, boolean>>({})
  const [versionMap, setVersionMap] = useState<VersionMap>({})
  const [loadingVersions, setLoadingVersions] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    async function loadAll() {
      setLoadingVersions(true)
      const map: VersionMap = {}
      const initSel: Record<string, boolean> = {}

      await Promise.all(
        eligibleCards.map(async (card) => {
          const allVersions: EstimateVersionSummary[] = []

          // Load original (V0) from estimate task
          if (card.estimate_task_id) {
            try {
              let versions = await getVersions(card.estimate_task_id)
              if (versions.length === 0) {
                try {
                  await initEstimateVersionFromResult(card.estimate_task_id)
                  versions = await getVersions(card.estimate_task_id)
                } catch {
                  // task not completed yet
                }
              }
              allVersions.push(...versions.filter((v) => !v.is_rolled_back))
            } catch {
              // ignore
            }
          }

          // Load V1–V5 from optimization task
          if (card.optimization_task_id) {
            try {
              const versions = await getVersions(card.optimization_task_id)
              allVersions.push(...versions.filter((v) => !v.is_rolled_back))
            } catch {
              // ignore
            }
          }

          // Deduplicate by version_label — keep highest version_number
          const byLabel = new Map<string, EstimateVersionSummary>()
          for (const v of allVersions) {
            const existing = byLabel.get(v.version_label)
            if (!existing || v.version_number > existing.version_number) {
              byLabel.set(v.version_label, v)
            }
          }

          // Order by VERSION_TYPES order
          const ordered: EstimateVersionSummary[] = []
          for (const vt of VERSION_TYPES) {
            const found = byLabel.get(vt.key)
            if (found) ordered.push(found)
          }
          // Append unknown labels at the end
          for (const v of byLabel.values()) {
            if (!VERSION_TYPES.find((vt) => vt.key === v.version_label)) {
              ordered.push(v)
            }
          }

          map[card.id] = ordered

          // Pre-select: if card has primary_version_id and it's in the list, select it
          // otherwise pre-select the last available version
          if (ordered.length > 0) {
            let preselect: EstimateVersionSummary | undefined
            if (card.primary_version_id) {
              preselect = ordered.find((v) => v.id === card.primary_version_id)
            }
            if (!preselect) preselect = ordered[ordered.length - 1]
            initSel[selKey(card.id, preselect.id)] = true
          }
        }),
      )

      setVersionMap(map)
      setSelectedItems(initSel)
      setLoadingVersions(false)
    }
    loadAll()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const handleToggle = (cardId: string, versionId: string) => {
    const k = selKey(cardId, versionId)
    setSelectedItems((prev) => ({ ...prev, [k]: !prev[k] }))
  }

  const handleConfirm = async () => {
    setError('')
    const sections: SectionInput[] = []
    for (const card of eligibleCards) {
      for (const version of versionMap[card.id] ?? []) {
        if (selectedItems[selKey(card.id, version.id)]) {
          sections.push({ card_id: card.id, version_id: version.id })
        }
      }
    }
    if (sections.length === 0) {
      setError('Выберите хотя бы одну версию сметы')
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

  const versionLabel = (v: EstimateVersionSummary) => {
    const match = VERSION_TYPES.find((vt) => vt.key === v.version_label)
    return match ? match.label : v.version_display_name
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
          Выберите сметы для включения в сводную.
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {eligibleCards.map((card) => {
              const versions = versionMap[card.id] ?? []
              return (
                <div
                  key={card.id}
                  style={{
                    border: '1px solid #e2e8f0',
                    borderRadius: '10px',
                    overflow: 'hidden',
                  }}
                >
                  {/* Card header */}
                  <div style={{
                    padding: '10px 14px',
                    background: '#f8fafc',
                    borderBottom: versions.length > 0 ? '1px solid #e2e8f0' : 'none',
                    fontWeight: 600,
                    fontSize: '13px',
                    color: '#1e293b',
                  }}>
                    {card.name}
                  </div>

                  {/* Version checkboxes */}
                  {versions.length === 0 ? (
                    <div style={{ padding: '12px 14px', fontSize: '12px', color: '#94a3b8' }}>
                      Нет доступных версий
                    </div>
                  ) : (
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '2px', padding: '8px' }}>
                      {versions.map((v) => {
                        const k = selKey(card.id, v.id)
                        const isChecked = !!selectedItems[k]
                        return (
                          <label
                            key={v.id}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '8px',
                              padding: '8px 10px',
                              borderRadius: '7px',
                              cursor: 'pointer',
                              background: isChecked ? '#eff6ff' : 'transparent',
                              border: isChecked ? '1px solid #bfdbfe' : '1px solid transparent',
                              transition: 'all 0.13s',
                              userSelect: 'none',
                            }}
                          >
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => handleToggle(card.id, v.id)}
                              style={{ width: 15, height: 15, accentColor: '#3b82f6', cursor: 'pointer', flexShrink: 0 }}
                            />
                            <span style={{ fontSize: '13px', color: isChecked ? '#1d4ed8' : '#475569', fontWeight: isChecked ? 600 : 400 }}>
                              {versionLabel(v)}
                            </span>
                          </label>
                        )
                      })}
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
