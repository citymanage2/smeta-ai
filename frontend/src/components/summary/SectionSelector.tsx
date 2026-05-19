import React, { useEffect, useState } from 'react'
import { Star } from 'lucide-react'
import { WorkflowCard } from '../../types/workflow'
import { EstimateVersionSummary } from '../../types'
import { getVersions } from '../../api/estimateVersions'
import { setPrimaryVersion } from '../../api/summaryEstimate'
import { SectionInput } from '../../types/summary'
import { LumaSpin } from '../ui/LumaSpin'

interface Props {
  cards: WorkflowCard[]
  onConfirm: (sections: SectionInput[]) => Promise<void>
  onClose: () => void
}

type VersionMap = Record<string, EstimateVersionSummary[]>

function getBestVersionId(card: WorkflowCard, versions: EstimateVersionSummary[]): string | null {
  if (card.primary_version_id) {
    const found = versions.find((v) => v.id === card.primary_version_id && !v.is_rolled_back)
    if (found) return found.id
  }
  const active = versions.filter((v) => !v.is_rolled_back)
  if (active.length === 0) return null
  return active[active.length - 1].id
}

const SectionSelector: React.FC<Props> = ({ cards, onConfirm, onClose }) => {
  const eligibleCards = cards.filter(
    (c) => c.estimate_task_id || c.optimization_task_id,
  )

  const [checked, setChecked] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {}
    eligibleCards.forEach((c) => { init[c.id] = true })
    return init
  })
  const [selectedVersionIds, setSelectedVersionIds] = useState<Record<string, string>>({})
  const [versionMap, setVersionMap] = useState<VersionMap>({})
  const [primaryVersionIds, setPrimaryVersionIds] = useState<Record<string, string | null>>(() => {
    const init: Record<string, string | null> = {}
    eligibleCards.forEach((c) => { init[c.id] = c.primary_version_id })
    return init
  })
  const [loadingVersions, setLoadingVersions] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')
  const [settingPrimary, setSettingPrimary] = useState<string | null>(null)

  useEffect(() => {
    async function loadAll() {
      setLoadingVersions(true)
      const map: VersionMap = {}
      const initSel: Record<string, string> = {}

      await Promise.all(
        eligibleCards.map(async (card) => {
          const taskId = card.estimate_task_id
          if (!taskId) return
          try {
            const versions = await getVersions(taskId)
            map[card.id] = versions
            const best = getBestVersionId(card, versions)
            if (best) initSel[card.id] = best
          } catch {
            map[card.id] = []
          }
        }),
      )

      setVersionMap(map)
      setSelectedVersionIds(initSel)
      setLoadingVersions(false)
    }
    loadAll()
  }, [])

  const handleToggleCard = (cardId: string) => {
    setChecked((prev) => ({ ...prev, [cardId]: !prev[cardId] }))
  }

  const handleVersionChange = (cardId: string, versionId: string) => {
    setSelectedVersionIds((prev) => ({ ...prev, [cardId]: versionId }))
  }

  const handleSetPrimary = async (card: WorkflowCard, versionId: string) => {
    setSettingPrimary(card.id)
    try {
      await setPrimaryVersion(card.id, versionId)
      setPrimaryVersionIds((prev) => ({ ...prev, [card.id]: versionId }))
    } catch {
      // silent
    } finally {
      setSettingPrimary(null)
    }
  }

  const handleConfirm = async () => {
    setError('')
    const sections: SectionInput[] = eligibleCards
      .filter((c) => checked[c.id] && selectedVersionIds[c.id])
      .map((c) => ({ card_id: c.id, version_id: selectedVersionIds[c.id] }))

    if (sections.length === 0) {
      setError('Выберите хотя бы один раздел с версией')
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
          maxHeight: '80vh',
          overflowY: 'auto',
          boxShadow: '0 8px 40px rgba(0,0,0,0.18)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ margin: '0 0 6px', fontSize: '18px', fontWeight: 700, color: '#0f172a' }}>
          Создать сводную себестоимость
        </h2>
        <p style={{ margin: '0 0 20px', fontSize: '13px', color: '#64748b' }}>
          Выберите разделы и версии смет для включения в сводную.
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
              const versions = (versionMap[card.id] ?? []).filter((v) => !v.is_rolled_back)
              const isChecked = checked[card.id]
              const primaryId = primaryVersionIds[card.id]

              return (
                <div
                  key={card.id}
                  style={{
                    border: isChecked ? '1.5px solid #93c5fd' : '1px solid #e2e8f0',
                    borderRadius: '10px',
                    padding: '12px 14px',
                    background: isChecked ? '#f0f9ff' : '#fafafa',
                    transition: 'all 0.15s',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: versions.length > 0 ? '10px' : 0 }}>
                    <input
                      type="checkbox"
                      checked={isChecked}
                      onChange={() => handleToggleCard(card.id)}
                      style={{ width: 16, height: 16, cursor: 'pointer', accentColor: '#3b82f6' }}
                    />
                    <span style={{ fontWeight: 600, fontSize: '14px', color: '#1e293b', flex: 1 }}>
                      {card.name}
                    </span>
                    {card.optimization_task_id && (
                      <span style={{ fontSize: '11px', color: '#7c3aed', fontWeight: 600, background: '#f5f3ff', padding: '2px 7px', borderRadius: '6px' }}>
                        оптимизировано
                      </span>
                    )}
                  </div>

                  {versions.length === 0 ? (
                    <div style={{ fontSize: '12px', color: '#94a3b8', paddingLeft: '26px' }}>
                      Нет доступных версий
                    </div>
                  ) : (
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', paddingLeft: '26px' }}>
                      <select
                        value={selectedVersionIds[card.id] ?? ''}
                        onChange={(e) => handleVersionChange(card.id, e.target.value)}
                        disabled={!isChecked}
                        style={{
                          flex: 1,
                          padding: '5px 8px',
                          fontSize: '13px',
                          border: '1px solid #e2e8f0',
                          borderRadius: '6px',
                          background: '#fff',
                          color: isChecked ? '#1e293b' : '#94a3b8',
                          cursor: isChecked ? 'pointer' : 'not-allowed',
                          outline: 'none',
                        }}
                      >
                        {versions.map((v) => (
                          <option key={v.id} value={v.id}>
                            {v.version_display_name}
                            {v.id === primaryId ? ' ★' : ''}
                          </option>
                        ))}
                      </select>

                      <button
                        title={
                          selectedVersionIds[card.id] === primaryId
                            ? 'Главная версия уже установлена'
                            : 'Сделать главной для этой карточки'
                        }
                        disabled={!isChecked || settingPrimary === card.id || !selectedVersionIds[card.id]}
                        onClick={() => handleSetPrimary(card, selectedVersionIds[card.id])}
                        style={{
                          background: 'none',
                          border: '1px solid #e2e8f0',
                          borderRadius: '6px',
                          padding: '5px 7px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          color: selectedVersionIds[card.id] === primaryId ? '#f59e0b' : '#cbd5e1',
                          transition: 'color 0.15s',
                        }}
                        onMouseEnter={(e) => { if (selectedVersionIds[card.id] !== primaryId) (e.currentTarget as HTMLElement).style.color = '#f59e0b' }}
                        onMouseLeave={(e) => { if (selectedVersionIds[card.id] !== primaryId) (e.currentTarget as HTMLElement).style.color = '#cbd5e1' }}
                      >
                        {settingPrimary === card.id
                          ? <LumaSpin size="sm" color="#f59e0b" />
                          : <Star size={14} fill={selectedVersionIds[card.id] === primaryId ? '#f59e0b' : 'none'} />
                        }
                      </button>
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
