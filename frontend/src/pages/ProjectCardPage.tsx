import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft, Info } from 'lucide-react'
import Layout from '../components/Layout'
import { LumaSpin } from '../components/ui/LumaSpin'
import { useKanbanStore, computeGuard } from '../stores/kanban'
import {
  PipelineStepper,
  PIPELINE_STAGES,
  computeNodeState,
  stageTask,
} from '../components/pipeline/PipelineStepper'
import { CardStageContent } from '../components/kanban/CardStageContent'
import StageProcessingPanel from '../components/card/StageProcessingPanel'
import DocumentEditor from '../components/editor/DocumentEditor'
import { WorkflowCard, KanbanStage } from '../types/workflow'
import { DocumentKind } from '../api/documents'
import { EditorTab } from '../stores/documentEditor'

// Этапы карточки и типы документов названы одинаково, и все четыре открываются
// одним редактором — отдельного отображения не нужно.
const EMBEDDED_EDITOR_STAGES: ReadonlySet<KanbanStage> = new Set<KanbanStage>([
  'list', 'completeness', 'estimate', 'optimization',
])

const STAGE_TITLE: Record<string, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
}

// ---------------------------------------------------------------------------
// Начальный выбранный этап: показываем то, что происходит/требует внимания
// (идёт → ошибка → первый незапущенный ПОСЛЕ последнего готового → последний
// готовый). Важно: не открывать пустую форму пропущенного раннего этапа
// (напр. опциональную «Полноту»), если дальше уже есть завершённые Смета/
// Оптимизация — иначе готовая смета выглядит незавершённой.
// ---------------------------------------------------------------------------
function defaultStage(card: WorkflowCard): KanbanStage {
  const states = PIPELINE_STAGES.map((s) => ({ s, st: computeNodeState(card, s) }))
  const running = states.find((x) => x.st === 'run' || x.st === 'error')
  if (running) return running.s
  const lastDoneIdx = states.map((x) => x.st).lastIndexOf('done')
  const wait = states.find((x, i) => x.st === 'wait' && i > lastDoneIdx)
  if (wait) return wait.s
  const lastDone = lastDoneIdx >= 0 ? states[lastDoneIdx] : undefined
  return lastDone?.s ?? card.stage
}

const ProjectCardPage: React.FC = () => {
  const { projectId, cardId } = useParams<{ projectId: string; cardId: string }>()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { cards, fetchCards } = useKanbanStore()

  const [initialLoad, setInitialLoad] = useState(true)
  const [selectedStage, setSelectedStage] = useState<KanbanStage | null>(null)
  const [softDismissed, setSoftDismissed] = useState(false)
  const initializedRef = useRef(false)

  const card = cards.find((c) => c.id === cardId) ?? null

  const refetch = useCallback(() => {
    if (projectId) fetchCards(projectId)
  }, [projectId, fetchCards])

  // Этап живёт в адресе: ссылку на конкретный этап можно скинуть коллеге,
  // и по ней откроется ровно то, что было на экране.
  const stageFromUrl = searchParams.get('stage') as KanbanStage | null

  // Загрузка + поллинг через тот же стор, что канбан/SmetaList — данные не дублируются.
  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    let intervalId: ReturnType<typeof setInterval> | undefined

    const poll = () => { if (!document.hidden) fetchCards(projectId) }

    const handleVisibility = () => {
      if (document.hidden) {
        if (intervalId !== undefined) { clearInterval(intervalId); intervalId = undefined }
      } else if (intervalId === undefined) {
        fetchCards(projectId)
        intervalId = setInterval(poll, 5000)
      }
    }

    ;(async () => {
      await fetchCards(projectId)
      if (!cancelled) setInitialLoad(false)
    })()
    intervalId = setInterval(poll, 5000)
    document.addEventListener('visibilitychange', handleVisibility)

    return () => {
      cancelled = true
      if (intervalId !== undefined) clearInterval(intervalId)
      document.removeEventListener('visibilitychange', handleVisibility)
    }
  }, [projectId, fetchCards])

  // Первичный выбор этапа — один раз, как только смета загрузилась.
  // Дальше степпер продвигается визуально сам (по статусам задач),
  // а выбранный этап меняется только по клику пользователя.
  useEffect(() => {
    if (card && !initializedRef.current) {
      initializedRef.current = true
      const known = PIPELINE_STAGES.includes(stageFromUrl as KanbanStage)
      setSelectedStage(known ? (stageFromUrl as KanbanStage) : defaultStage(card))
    }
  }, [card, stageFromUrl])

  if (initialLoad && !card) {
    return (
      <Layout>
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '60vh' }}>
          <LumaSpin size="lg" color="#3b82f6" />
        </div>
      </Layout>
    )
  }

  if (!card) {
    return (
      <Layout>
        <div style={{ padding: '32px', textAlign: 'center', color: '#ef4444', fontSize: '14px' }}>
          Смета не найдена
        </div>
      </Layout>
    )
  }

  const stageForContent: KanbanStage = selectedStage ?? card.stage
  const currentTask = stageTask(card, stageForContent)
  const showEditor = !!currentTask
    && currentTask.status === 'completed'
    && EMBEDDED_EDITOR_STAGES.has(stageForContent)
  const guard = computeGuard(card, stageForContent)
  const showSoft =
    guard.blockType === 'soft' && !stageTask(card, stageForContent) && !softDismissed

  // Версия и вкладка живут в адресе рядом с этапом: скопированная ссылка
  // должна открыть у коллеги ровно то, что видит отправитель. `replace`, чтобы
  // переключение вкладок не забивало историю браузера.
  const handleEditorState = useCallback(
    (state: { versionId: string | null; tab: string }) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        if (state.versionId) next.set('version', state.versionId)
        else next.delete('version')
        if (state.tab && state.tab !== 'all') next.set('tab', state.tab)
        else next.delete('tab')
        return next
      }, { replace: true })
    },
    [setSearchParams],
  )

  const handleSelect = (stage: KanbanStage) => {
    setSelectedStage(stage)
    setSoftDismissed(false)
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      next.set('stage', stage)
      return next
    }, { replace: true })
  }

  return (
    <Layout>
      {/* Со встроенной таблицей странице нужна вся ширина: в 720 px смета не помещается. */}
      <div style={{ maxWidth: showEditor ? 1400 : 720, margin: '0 auto', padding: '24px 16px' }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '20px' }}>
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
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: '#0f172a', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {card.name}
            </h1>
          </div>
        </div>

        {/* Пайплайн-дорожка (КП-2): 4 этапа, продвижение автоматическое, без drag */}
        <PipelineStepper card={card} selectedStage={stageForContent} onSelect={handleSelect} />

        {/* Soft-гейт (КП-3): предупреждение на выбранном этапе, не блокирующее */}
        {showSoft && (
          <div
            style={{
              display: 'flex', alignItems: 'flex-start', gap: '8px',
              background: '#fffbeb', border: '1px solid #fcd34d',
              borderRadius: '12px', padding: '12px 14px', marginTop: '14px',
              fontSize: '13px', color: '#92400e',
            }}
          >
            <Info size={15} color="#d97706" style={{ flexShrink: 0, marginTop: 1 }} />
            <span style={{ flex: 1, lineHeight: 1.5 }}>{guard.message}</span>
            <button
              onClick={() => setSoftDismissed(true)}
              style={{
                background: 'rgba(255,255,255,0.7)', color: '#92400e',
                border: '1px solid #fcd34d', borderRadius: '8px',
                padding: '4px 12px', fontSize: '12px', fontWeight: 600,
                cursor: 'pointer', flexShrink: 0,
              }}
            >
              Продолжить
            </button>
          </div>
        )}

        {/* Контент выбранного этапа — переиспользуем CardStageContent (вся логика
            загрузки файлов и запуска джобов живёт там; здесь не дублируется). */}
        <div
          style={{
            marginTop: '16px',
            background: 'rgba(255,255,255,0.9)',
            border: '1px solid #e2e8f0',
            borderRadius: '16px',
            padding: '18px',
            boxShadow: '0 4px 24px rgba(0,0,0,0.04)',
          }}
        >
          <CardStageContent card={{ ...card, stage: stageForContent }} />

          {/* Ход обработки этапа — переехал сюда со страницы задачи. */}
          {currentTask?.id && (
            <div style={{ marginTop: '14px' }}>
              <StageProcessingPanel taskId={currentTask.id} onChanged={refetch} />
            </div>
          )}
        </div>

        {/* Таблица этапа прямо на странице; «на весь экран» — в её панели. */}
        {showEditor && (
          <div style={{ marginTop: '16px' }}>
            <DocumentEditor
              cardId={card.id}
              kind={stageForContent as DocumentKind}
              title={STAGE_TITLE[stageForContent] ?? card.name}
              initialVersionId={searchParams.get('version') ?? undefined}
              initialTab={(searchParams.get('tab') as EditorTab | null) ?? undefined}
              onStateChange={handleEditorState}
              onApplied={refetch}
            />
          </div>
        )}
      </div>
    </Layout>
  )
}

export default ProjectCardPage
