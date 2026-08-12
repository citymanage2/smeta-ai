import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import Layout from '../components/Layout'
import DocumentEditor from '../components/editor/DocumentEditor'
import { DocumentKind } from '../api/documents'
import { EditorTab } from '../stores/documentEditor'
import { CardDetail, StageDetail, getCardFilesMeta } from '../api/workflowCards'

/**
 * Страница документа — единственный способ открыть таблицу.
 *
 * Раньше «Открыть онлайн» показывало редактор окном поверх экрана: у документа
 * не было адреса, ссылку коллеге отправить было нельзя, а «Назад» уводило с
 * экрана целиком. Теперь документ — обычная страница, а окна-оверлея в проекте
 * не осталось (план `plans/2026-08-13-redaktor-stranicej.md`).
 */

/** Типы документов, которые открываются этой страницей. Раздел сводной живёт
 *  во вкладках сводной и сюда не попадает. */
const PAGE_KINDS = ['list', 'completeness', 'estimate', 'optimization'] as const
type PageKind = (typeof PAGE_KINDS)[number]

const KIND_LABEL: Record<PageKind, string> = {
  list: 'Перечень',
  completeness: 'Полнота',
  estimate: 'Смета',
  optimization: 'Оптимизация',
}

/** Тип документа и стадия карточки названы одинаково — отдельного отображения
 *  не нужно, но метаданные файлов лежат по своим полям. */
function stageOf(meta: CardDetail | null, kind: PageKind): StageDetail | null {
  if (!meta) return null
  switch (kind) {
    case 'list': return meta.source_stage
    case 'completeness': return meta.completeness_stage
    case 'estimate': return meta.estimate_stage
    case 'optimization': return meta.optimization_stage
  }
}

const DocumentPage: React.FC = () => {
  const { projectId, cardId, kind } = useParams<{ projectId: string; cardId: string; kind: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const [meta, setMeta] = useState<CardDetail | null>(null)

  const slot = searchParams.get('slot')
  const indexParam = searchParams.get('index')
  const isInput = slot === 'input'
  // Номер файла из адреса может прийти любым: правленую руками ссылку нельзя
  // превращать в запрос с `index=NaN`.
  const parsedIndex = indexParam === null ? NaN : Number(indexParam)
  const fileIndex = Number.isInteger(parsedIndex) ? parsedIndex : undefined

  const known = PAGE_KINDS.includes(kind as PageKind)

  // Имя карточки и имя файла — только для заголовка. Запрос не блокирует
  // таблицу: она грузится своим ходом, заголовок подставится, когда приедет.
  useEffect(() => {
    if (!cardId || !known) return
    let cancelled = false
    getCardFilesMeta(cardId)
      .then((data) => { if (!cancelled) setMeta(data) })
      .catch(() => { /* Молча: без заголовка страница работает */ })
    return () => { cancelled = true }
  }, [cardId, known])

  // Версия и вкладки живут в адресе: скопированная ссылка должна открыть у
  // коллеги ровно то, что видит отправитель. `replace`, чтобы переключение
  // вкладок не забивало историю браузера.
  const handleEditorState = useCallback(
    (state: { versionId: string | null; tab: string; sheet: string | null; collapsed: boolean }) => {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev)
        if (state.versionId) next.set('version', state.versionId)
        else next.delete('version')
        if (state.tab && state.tab !== 'all') next.set('tab', state.tab)
        else next.delete('tab')
        if (state.sheet) next.set('sheet', state.sheet)
        else next.delete('sheet')
        // Свёртка одинаковых позиций — тоже часть того, что видит отправитель
        // ссылки: в свёрнутом виде таблица читается иначе.
        if (state.collapsed) next.set('collapsed', '1')
        else next.delete('collapsed')
        return next
      }, { replace: true })
    },
    [setSearchParams],
  )

  // «Назад» возвращает туда, откуда пришли — на доску, в список смет или в
  // карточку. По прямой ссылке возвращаться некуда: ведём на карточку.
  const goBack = useCallback(() => {
    if (location.key !== 'default') navigate(-1)
    else navigate(`/projects/${projectId}/cards/${cardId}?stage=${kind}`)
  }, [location.key, navigate, projectId, cardId, kind])

  const title = useMemo(() => {
    if (!known) return ''
    const label = isInput ? 'Исходный файл' : KIND_LABEL[kind as PageKind]
    const stage = stageOf(meta, kind as PageKind)
    const fileName = isInput
      ? stage?.input_files.find((f) => f.index === fileIndex)?.name
      : stage?.result_files.find((f) => f.slot === slot)?.file_name
    return fileName ? `${label} — ${fileName}` : label
  }, [known, isInput, kind, meta, fileIndex, slot])

  if (!projectId || !cardId || !known) {
    return <Navigate to={cardId && projectId ? `/projects/${projectId}/cards/${cardId}` : '/system'} replace />
  }

  return (
    <Layout>
      {/* Таблице нужна вся ширина: в колонку 720 px смета не помещается.
          Сверху отступа своего нет — область прокрутки Layout уже отбивает
          `MAIN_PADDING_TOP`, и второй отступ отжимал бы таблицу от шапки
          на пустую полосу в полсотни пикселей. */}
      <div style={{ maxWidth: 1600, margin: '0 auto', padding: '0 16px 24px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px' }}>
          <button
            onClick={goBack}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              background: 'none', border: '1px solid #e2e8f0', borderRadius: '8px',
              padding: '6px 12px', cursor: 'pointer', color: '#64748b', fontSize: '13px',
              transition: 'all 0.15s', flexShrink: 0,
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#93c5fd'; (e.currentTarget as HTMLElement).style.color = '#3b82f6' }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = '#e2e8f0'; (e.currentTarget as HTMLElement).style.color = '#64748b' }}
          >
            <ArrowLeft size={14} />
            Назад
          </button>
          <div style={{ flex: 1, minWidth: 0 }}>
            <h1 style={{
              margin: 0, fontSize: '18px', fontWeight: 700, color: '#0f172a',
              overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            }}>
              {meta?.name ?? 'Документ'}
            </h1>
          </div>
        </div>

        <DocumentEditor
          cardId={cardId}
          kind={kind as DocumentKind}
          fileSlot={isInput ? 'input' : undefined}
          fileIndex={isInput ? fileIndex : undefined}
          title={title}
          fullHeight
          initialVersionId={searchParams.get('version') ?? undefined}
          initialTab={(searchParams.get('tab') as EditorTab | null) ?? undefined}
          initialSheet={searchParams.get('sheet') ?? undefined}
          initialCollapsed={searchParams.get('collapsed') === '1'}
          onStateChange={handleEditorState}
        />
      </div>
    </Layout>
  )
}

export default DocumentPage
