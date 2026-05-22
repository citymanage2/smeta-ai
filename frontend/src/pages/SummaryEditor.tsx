import React, { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, LayoutList } from 'lucide-react'
import Layout from '../components/Layout'
import { LumaSpin } from '../components/ui/LumaSpin'
import SectionSelector from '../components/summary/SectionSelector'
import SummaryEditorTabs from '../components/summary/SummaryEditorTabs'
import { useSummaryEditorStore } from '../stores/summaryEditorStore'
import { getWorkflowCards } from '../api/workflowCards'
import { createSummary } from '../api/summaryEstimate'
import { WorkflowCard } from '../types/workflow'
import { SectionInput } from '../types/summary'

const SummaryEditor: React.FC = () => {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const { loadSummary, reset } = useSummaryEditorStore()

  const [cards, setCards] = useState<WorkflowCard[]>([])
  const [projectName] = useState<string | undefined>()
  const [loading, setLoading] = useState(true)
  const [hasSummary, setHasSummary] = useState(false)
  const [showSelector, setShowSelector] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!projectId) return
    setLoading(true)
    setError('')
    try {
      const [cardsData] = await Promise.all([
        getWorkflowCards(projectId),
      ])
      setCards(cardsData)

      try {
        await loadSummary(projectId)
        setHasSummary(true)
      } catch (err: unknown) {
        const axiosErr = err as { response?: { status?: number } }
        if (axiosErr?.response?.status === 404) {
          setHasSummary(false)
          setShowSelector(true)
        } else {
          throw err
        }
      }
    } catch {
      setError('Не удалось загрузить данные проекта')
    } finally {
      setLoading(false)
    }
  }, [projectId, loadSummary])

  useEffect(() => {
    load()
    return () => { reset() }
  }, [load, reset])

  const handleCreate = async (selectedSections: SectionInput[]) => {
    if (!projectId) return
    await createSummary(projectId, { sections: selectedSections })
    await loadSummary(projectId)
    setHasSummary(true)
    setShowSelector(false)
  }

  if (loading) {
    return (
      <Layout>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
          <LumaSpin size="lg" color="#3b82f6" />
        </div>
      </Layout>
    )
  }

  if (error) {
    return (
      <Layout>
        <div style={{ textAlign: 'center', padding: '48px', color: '#dc2626', fontSize: '14px' }}>
          {error}
        </div>
      </Layout>
    )
  }

  return (
    <Layout>
      <div style={{ maxWidth: 1400, margin: '0 auto', padding: '24px 16px', height: 'calc(100vh - 64px)', display: 'flex', flexDirection: 'column' }}>

        {/* ── Header / Breadcrumb ── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px', flexShrink: 0 }}>
          <button
            onClick={() => navigate(`/projects/${projectId}`)}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              background: 'none', border: '1px solid #e2e8f0', borderRadius: '8px',
              padding: '6px 12px', cursor: 'pointer', color: '#64748b', fontSize: '13px',
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#93c5fd'; (e.currentTarget as HTMLElement).style.color = '#3b82f6' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#e2e8f0'; (e.currentTarget as HTMLElement).style.color = '#64748b' }}
          >
            <ArrowLeft size={14} />
            К проекту
          </button>

          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '14px', color: '#94a3b8' }}>
            <LayoutList size={14} />
            <span>Сводная себестоимость</span>
          </div>

          {hasSummary && (
            <div style={{ marginLeft: 'auto', display: 'flex', gap: '8px' }}>
              <button
                onClick={() => setShowSelector(true)}
                style={{
                  padding: '6px 14px', fontSize: '13px', fontWeight: 500,
                  border: '1px solid #e2e8f0', borderRadius: '8px',
                  background: '#fff', color: '#475569', cursor: 'pointer',
                }}
              >
                Изменить разделы
              </button>
            </div>
          )}
        </div>

        {/* ── Content ── */}
        {!hasSummary ? (
          <div style={{
            flex: 1, display: 'flex', flexDirection: 'column',
            alignItems: 'center', justifyContent: 'center', gap: '16px',
          }}>
            <div style={{ textAlign: 'center' }}>
              <div style={{ fontSize: '48px', marginBottom: '12px' }}>📊</div>
              <h2 style={{ margin: '0 0 8px', fontSize: '20px', fontWeight: 700, color: '#1e293b' }}>
                Сводная себестоимость не создана
              </h2>
              <p style={{ margin: '0 0 24px', fontSize: '14px', color: '#64748b', maxWidth: '420px' }}>
                Выберите разделы и версии смет для формирования сводной таблицы стоимости проекта.
              </p>
            </div>
            <button
              onClick={() => setShowSelector(true)}
              style={{
                padding: '10px 28px', fontSize: '15px', fontWeight: 600,
                borderRadius: '10px', border: 'none',
                background: '#3b82f6', color: '#fff', cursor: 'pointer',
                boxShadow: '0 4px 12px rgba(59,130,246,0.3)',
                transition: 'all 0.15s',
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.background = '#2563eb' }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.background = '#3b82f6' }}
            >
              + Создать сводную
            </button>
          </div>
        ) : (
          <div style={{ flex: 1, minHeight: 0 }}>
            <SummaryEditorTabs projectId={projectId!} projectName={projectName} />
          </div>
        )}

        {/* ── Section Selector Modal ── */}
        {showSelector && (
          <SectionSelector
            cards={cards}
            onConfirm={handleCreate}
            onClose={() => setShowSelector(false)}
          />
        )}
      </div>
    </Layout>
  )
}

export default SummaryEditor
