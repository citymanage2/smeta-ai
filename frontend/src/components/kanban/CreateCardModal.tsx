import React, { useState, useRef } from 'react'
import { useKanbanStore } from '../../stores/kanban'
import { KanbanStage } from '../../types/workflow'

const FILE_SIZE_LIMIT = 50 * 1024 * 1024

interface Props {
  projectId: string
  onClose: () => void
  stage?: KanbanStage
}

export function CreateCardModal({ projectId, onClose, stage }: Props) {
  const isListStage = stage === 'list'
  const isOptimization = stage === 'optimization'
  const { createCard, startTask, setPendingListTask } = useKanbanStore()
  const [name, setName] = useState('')
  const [taskType, setTaskType] = useState<'LIST_FROM_PROJECT' | 'LIST_FROM_GRAND'>('LIST_FROM_PROJECT')
  const [file, setFile] = useState<File | null>(null)
  const [fileError, setFileError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    if (f && f.size > FILE_SIZE_LIMIT) {
      setFileError('Файл превышает 50 МБ')
      setFile(null)
    } else {
      setFileError(null)
      setFile(f)
    }
  }

  const needsFile = isListStage || isOptimization
  const canSubmit = needsFile
    ? name.trim().length > 0 && file !== null && !loading
    : name.trim().length > 0 && !loading

  const handleSubmit = async () => {
    if (!canSubmit) return
    setLoading(true)
    try {
      const card = await createCard(projectId, name.trim(), stage)
      if (isListStage) {
        setPendingListTask(card.id, { task_type: taskType, files: [file!] })
      } else if (isOptimization) {
        try {
          await startTask(card.id, { task_type: 'ESTIMATE_OPTIMIZATION', file: file! })
        } catch {
          // Карточка создана, задача не запустилась — пользователь запустит с карточки
        }
      }
      onClose()
    } catch {
      setLoading(false)
    }
  }

  const overlayStyle: React.CSSProperties = {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.3)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  }

  const modalStyle: React.CSSProperties = {
    background: '#fff',
    borderRadius: '12px',
    padding: '24px',
    width: '420px',
    maxWidth: '95vw',
    boxShadow: '0 8px 32px rgba(0,0,0,0.15)',
  }

  const title = isListStage
    ? 'Новая смета · Перечень'
    : isOptimization
    ? 'Новая смета · Оптимизация'
    : 'Новая смета'

  return (
    <div style={overlayStyle} onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div style={modalStyle}>
        <h3 style={{ margin: '0 0 16px', fontSize: '16px', color: '#1e293b' }}>
          {title}
        </h3>

        <div style={{ marginBottom: '12px' }}>
          <label style={{ fontSize: '13px', color: '#475569', display: 'block', marginBottom: '4px' }}>
            Название <span style={{ color: '#ef4444' }}>*</span>
          </label>
          <input
            autoFocus
            maxLength={255}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Название сметы"
            style={{
              width: '100%',
              boxSizing: 'border-box',
              border: '1px solid #e2e8f0',
              borderRadius: '6px',
              padding: '8px 10px',
              fontSize: '14px',
              outline: 'none',
            }}
            onKeyDown={(e) => { if (e.key === 'Enter' && !isListStage) handleSubmit() }}
          />
        </div>

        {isListStage && (
          <>
            <div style={{ marginBottom: '12px' }}>
              <div style={{ fontSize: '13px', color: '#475569', marginBottom: '8px', fontWeight: 500 }}>
                Тип перечня <span style={{ color: '#ef4444' }}>*</span>
              </div>
              {(['LIST_FROM_PROJECT', 'LIST_FROM_GRAND'] as const).map((t) => (
                <label key={t} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', marginBottom: '6px', cursor: 'pointer' }}>
                  <input type="radio" value={t} checked={taskType === t} onChange={() => setTaskType(t)} />
                  {t === 'LIST_FROM_PROJECT' ? 'Перечень из проекта' : 'Перечень из Гранд-сметы'}
                </label>
              ))}
            </div>
            <div style={{ marginBottom: '16px' }}>
              <label style={{ fontSize: '13px', color: '#475569', display: 'block', marginBottom: '4px' }}>
                Файл <span style={{ color: '#ef4444' }}>*</span>
              </label>
              <input ref={fileRef} type="file" style={{ fontSize: '13px' }} onChange={handleFileChange} />
              {fileError && <div style={{ color: '#dc2626', fontSize: '12px', marginTop: '4px' }}>{fileError}</div>}
            </div>
          </>
        )}

        {isOptimization && (
          <div style={{ marginBottom: '16px' }}>
            <label style={{ fontSize: '13px', color: '#475569', display: 'block', marginBottom: '4px' }}>
              Файл сметы <span style={{ color: '#ef4444' }}>*</span>
            </label>
            <input ref={fileRef} type="file" style={{ fontSize: '13px' }} onChange={handleFileChange} />
            {fileError && <div style={{ color: '#dc2626', fontSize: '12px', marginTop: '4px' }}>{fileError}</div>}
          </div>
        )}

        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
          <button
            onClick={onClose}
            style={{ border: '1px solid #e2e8f0', background: '#f8fafc', color: '#475569', borderRadius: '6px', padding: '8px 16px', fontSize: '14px', cursor: 'pointer' }}
          >
            Отмена
          </button>
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            style={{
              background: canSubmit ? '#3b82f6' : '#93c5fd',
              color: '#fff',
              border: 'none',
              borderRadius: '6px',
              padding: '8px 16px',
              fontSize: '14px',
              cursor: canSubmit ? 'pointer' : 'not-allowed',
            }}
          >
            {loading ? 'Создаю…' : 'Создать'}
          </button>
        </div>
      </div>
    </div>
  )
}
