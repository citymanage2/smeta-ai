import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import TaskTypeSelector from '../components/TaskTypeSelector';
import FileUpload from '../components/FileUpload';
import { TaskType, ProjectCard, TASK_TYPE_LABELS } from '../types';
import { createTask, getEstimateSources, EstimateSource } from '../api/tasks';
import { listProjects } from '../api/projects';

const TaskCreate: React.FC = () => {
  const navigate = useNavigate();
  const [taskType, setTaskType] = useState<TaskType>('LIST_FROM_GRAND');
  const [files, setFiles] = useState<File[]>([]);
  const [name, setName] = useState('');
  const [nameError, setNameError] = useState('');
  const nameUserEditedRef = useRef(false);
  const [prompt, setPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [submitStep, setSubmitStep] = useState<'upload' | 'create' | null>(null);
  const [error, setError] = useState('');
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [projectMode, setProjectMode] = useState<'none' | 'existing' | 'new'>('none');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [newProjectName, setNewProjectName] = useState('');

  // Path B (ESTIMATE_FROM_LIST from existing task)
  const [inputMode, setInputMode] = useState<'file' | 'task'>('file');
  const [estimateSources, setEstimateSources] = useState<EstimateSource[]>([]);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [selectedSourceTaskId, setSelectedSourceTaskId] = useState('');
  const [selectedStage, setSelectedStage] = useState<number>(1);

  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
  }, []);

  // Load estimate sources when Path B mode is selected
  useEffect(() => {
    if (taskType === 'ESTIMATE_FROM_LIST' && inputMode === 'task' && estimateSources.length === 0) {
      setSourcesLoading(true);
      getEstimateSources()
        .then(setEstimateSources)
        .catch(() => {})
        .finally(() => setSourcesLoading(false));
    }
  }, [taskType, inputMode, estimateSources.length]);

  // Reset input mode when task type changes
  useEffect(() => {
    if (taskType !== 'ESTIMATE_FROM_LIST') {
      setInputMode('file');
    }
    setSelectedSourceTaskId('');
    setSelectedStage(1);
  }, [taskType]);

  // Flat options: one entry per (task × stage) combination
  const estimateOptions = estimateSources.flatMap((s) =>
    s.stages.map((st) => ({
      key: `${s.task_id}:${st.stage}`,
      task_id: s.task_id,
      stage: st.stage,
      task_type: s.task_type,
      name: s.name,
      created_at: s.created_at,
      label: st.label,
      items_count: st.items_count,
    }))
  );

  const selectedKey = selectedSourceTaskId ? `${selectedSourceTaskId}:${selectedStage}` : '';

  const handleSourceKeyChange = (key: string) => {
    if (!key) {
      setSelectedSourceTaskId('');
      setSelectedStage(1);
      return;
    }
    const colonIdx = key.indexOf(':');
    const taskId = key.slice(0, colonIdx);
    const stage = Number(key.slice(colonIdx + 1));
    setSelectedSourceTaskId(taskId);
    setSelectedStage(stage);
    const opt = estimateOptions.find((o) => o.key === key);
    if (opt && !nameUserEditedRef.current && opt.name) {
      setName(`Смета из перечня: ${opt.name}`);
    }
  };

  // Auto-select when there is exactly one option
  useEffect(() => {
    if (estimateOptions.length === 1 && !selectedSourceTaskId) {
      handleSourceKeyChange(estimateOptions[0].key);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [estimateSources]);

  const buildAutoName = (type: TaskType, file: File): string => {
    const label = TASK_TYPE_LABELS[type] ?? type;
    const baseName = file.name.replace(/\.[^.]+$/, '');
    return `${label}: ${baseName}`;
  };

  // Auto-fill name when files change (only if user hasn't manually edited the field)
  useEffect(() => {
    if (!nameUserEditedRef.current && files.length > 0) {
      setName(buildAutoName(taskType, files[0]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [files]);

  // Auto-fill name when task type changes (only if user hasn't manually edited)
  useEffect(() => {
    if (!nameUserEditedRef.current && files.length > 0) {
      setName(buildAutoName(taskType, files[0]));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskType]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setNameError('');

    if (!name.trim()) {
      setNameError('Введите название задачи.');
      return;
    }

    const isPathB = taskType === 'ESTIMATE_FROM_LIST' && inputMode === 'task';

    if (!isPathB && files.length === 0) {
      setError('Добавьте хотя бы один файл для обработки.');
      return;
    }

    if (isPathB && !selectedSourceTaskId) {
      setError('Выберите задачу-источник.');
      return;
    }

    setSubmitting(true);
    setUploadPercent(0);
    setSubmitStep('upload');

    try {
      const formData = new FormData();
      formData.append('task_type', taskType);
      formData.append('name', name.trim());
      if (isPathB) {
        formData.append('source_task_id', selectedSourceTaskId);
        formData.append('source_stage', String(selectedStage));
      } else {
        if (prompt.trim()) {
          formData.append('prompt', prompt.trim());
        }
        files.forEach((file) => {
          formData.append('files', file);
        });
      }

      if (projectMode === 'existing' && selectedProjectId) {
        formData.append('project_id', selectedProjectId);
      } else if (projectMode === 'new' && newProjectName.trim()) {
        formData.append('project_name', newProjectName.trim());
      }

      const task = await createTask(formData, (pct) => {
        setUploadPercent(pct);
        if (pct >= 100) setSubmitStep('create');
      });
      if (!task.task_id) {
        setError('Задача создана, но ID не получен. Попробуйте обновить страницу.');
        return;
      }
      navigate(`/tasks/${task.task_id}/status`);
    } catch (err: unknown) {
      const axiosError = err as { response?: { data?: { detail?: string } }; request?: unknown };
      if (axiosError.request && !axiosError.response) {
        setError('Ошибка сети при загрузке, проверьте соединение и попробуйте ещё раз.');
      } else {
        setError(axiosError.response?.data?.detail ?? 'Ошибка при создании задачи. Попробуйте ещё раз.');
      }
    } finally {
      setSubmitting(false);
      setSubmitStep(null);
      setUploadPercent(0);
    }
  };

  return (
    <Layout>
      <div style={{ maxWidth: '720px', margin: '0 auto' }}>
        {/* Page title */}
        <div style={{ marginBottom: '28px' }}>
          <h2 style={{ margin: 0, fontSize: '26px', fontWeight: 700, color: '#0f172a' }}>
            Новая задача
          </h2>
          <p style={{ margin: '6px 0 0', color: '#64748b', fontSize: '15px' }}>
            Выберите тип задачи, загрузите файлы и нажмите «Создать задачу»
          </p>
        </div>

        {/* Form card */}
        <div
          style={{
            backgroundColor: '#ffffff',
            borderRadius: '12px',
            boxShadow: '0 1px 4px rgba(0,0,0,0.07)',
            padding: '32px',
            border: '1px solid #e2e8f0',
          }}
        >
          <form onSubmit={handleSubmit} noValidate>
            {/* Task type */}
            <div style={{ marginBottom: '24px' }}>
              <TaskTypeSelector value={taskType} onChange={setTaskType} disabled={submitting} />
            </div>

            {/* Path B toggle — only for ESTIMATE_FROM_LIST */}
            {taskType === 'ESTIMATE_FROM_LIST' && (
              <div style={{ marginBottom: '24px' }}>
                <label style={{ display: 'block', fontSize: '14px', fontWeight: 600, color: '#374151', marginBottom: '10px' }}>
                  Источник перечня
                </label>
                <div style={{ display: 'flex', gap: '8px' }}>
                  {(['file', 'task'] as const).map((mode) => (
                    <button
                      key={mode}
                      type="button"
                      disabled={submitting}
                      onClick={() => setInputMode(mode)}
                      style={{
                        padding: '8px 18px',
                        fontSize: '14px',
                        fontWeight: 500,
                        border: `1.5px solid ${inputMode === mode ? '#2563eb' : '#e2e8f0'}`,
                        borderRadius: '8px',
                        backgroundColor: inputMode === mode ? '#eff6ff' : '#ffffff',
                        color: inputMode === mode ? '#1d4ed8' : '#64748b',
                        cursor: submitting ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {mode === 'file' ? '📎 Загрузить файл' : '🗂 Из существующей задачи'}
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Path B: source task selector */}
            {taskType === 'ESTIMATE_FROM_LIST' && inputMode === 'task' ? (
              <div style={{ marginBottom: '24px' }}>
                {sourcesLoading ? (
                  <div style={{ fontSize: '14px', color: '#64748b' }}>Загрузка перечней...</div>
                ) : estimateOptions.length === 0 ? (
                  <div style={{ padding: '12px 16px', backgroundColor: '#fef9c3', border: '1px solid #fde047', borderRadius: '8px', fontSize: '14px', color: '#854d0e' }}>
                    Нет завершённых задач «Перечень из Гранд-сметы» или «Перечень из проекта».
                  </div>
                ) : (
                  <>
                    <label style={{ display: 'block', fontSize: '14px', fontWeight: 600, color: '#374151', marginBottom: '8px' }}>
                      Перечень-источник
                    </label>
                    <select
                      value={selectedKey}
                      onChange={(e) => handleSourceKeyChange(e.target.value)}
                      disabled={submitting}
                      style={{
                        width: '100%',
                        padding: '10px 12px',
                        border: '1.5px solid #e2e8f0',
                        borderRadius: '8px',
                        fontSize: '14px',
                        backgroundColor: '#fff',
                      }}
                    >
                      <option value="">— Выберите перечень —</option>
                      {(['LIST_FROM_GRAND', 'LIST_FROM_PROJECT'] as const).map((type) => {
                        const opts = estimateOptions.filter((o) => o.task_type === type);
                        if (opts.length === 0) return null;
                        const groupLabel = type === 'LIST_FROM_GRAND' ? 'Перечень из Гранд-сметы' : 'Перечень из проекта';
                        return (
                          <optgroup key={type} label={groupLabel}>
                            {opts.map((opt) => (
                              <option key={opt.key} value={opt.key}>
                                {opt.name || groupLabel} · {new Date(opt.created_at).toLocaleDateString('ru-RU')} · {opt.label} ({opt.items_count} поз.)
                              </option>
                            ))}
                          </optgroup>
                        );
                      })}
                    </select>
                  </>
                )}
              </div>
            ) : (
              /* File upload */
              <div style={{ marginBottom: '24px' }}>
                <FileUpload files={files} onChange={setFiles} />
              </div>
            )}

            {/* Task name */}
            <div style={{ marginBottom: '24px' }}>
              <label
                htmlFor="taskName"
                style={{
                  display: 'block',
                  fontSize: '14px',
                  fontWeight: 600,
                  color: '#374151',
                  marginBottom: '8px',
                }}
              >
                Название задачи <span style={{ color: '#dc2626' }}>*</span>
              </label>
              <input
                id="taskName"
                type="text"
                value={name}
                onChange={(e) => {
                  nameUserEditedRef.current = true;
                  setName(e.target.value);
                  if (e.target.value.trim()) setNameError('');
                }}
                placeholder="Заполняется автоматически после выбора файла"
                disabled={submitting}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  fontSize: '14px',
                  color: '#1e293b',
                  border: `1.5px solid ${nameError ? '#fca5a5' : '#e2e8f0'}`,
                  borderRadius: '8px',
                  outline: 'none',
                  boxSizing: 'border-box',
                  fontFamily: 'inherit',
                  backgroundColor: submitting ? '#f1f5f9' : '#ffffff',
                  transition: 'border-color 0.15s',
                }}
                onFocus={(e) => { if (!nameError) e.target.style.borderColor = '#2563eb'; }}
                onBlur={(e) => { e.target.style.borderColor = nameError ? '#fca5a5' : '#e2e8f0'; }}
              />
              {nameError && (
                <div style={{ marginTop: '4px', fontSize: '13px', color: '#dc2626' }}>
                  {nameError}
                </div>
              )}
            </div>

            {/* Prompt */}
            <div style={{ marginBottom: '28px' }}>
              <label
                htmlFor="prompt"
                style={{
                  display: 'block',
                  fontSize: '14px',
                  fontWeight: 600,
                  color: '#374151',
                  marginBottom: '8px',
                }}
              >
                Дополнительные инструкции{' '}
                <span style={{ color: '#94a3b8', fontWeight: 400 }}>(необязательно)</span>
              </label>
              <textarea
                id="prompt"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Опишите особые требования или уточнения для задачи..."
                rows={4}
                disabled={submitting}
                style={{
                  width: '100%',
                  padding: '10px 14px',
                  fontSize: '14px',
                  color: '#1e293b',
                  border: '1.5px solid #e2e8f0',
                  borderRadius: '8px',
                  resize: 'vertical',
                  outline: 'none',
                  boxSizing: 'border-box',
                  fontFamily: 'inherit',
                  backgroundColor: submitting ? '#f1f5f9' : '#ffffff',
                  transition: 'border-color 0.15s',
                }}
                onFocus={(e) => { e.target.style.borderColor = '#2563eb'; }}
                onBlur={(e) => { e.target.style.borderColor = '#e2e8f0'; }}
              />
            </div>

            {/* Project selector */}
            <div style={{ marginBottom: '24px' }}>
              <label style={{ display: 'block', fontSize: '14px', fontWeight: 600, color: '#374151', marginBottom: '10px' }}>
                Добавить в проект
              </label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                {(['none', 'existing', 'new'] as const).map((mode) => (
                  <label key={mode} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                    <input
                      type="radio"
                      name="projectMode"
                      value={mode}
                      checked={projectMode === mode}
                      onChange={() => setProjectMode(mode)}
                    />
                    <span style={{ fontSize: '14px', color: '#374151' }}>
                      {mode === 'none' ? 'Не добавлять' : mode === 'existing' ? 'Выбрать существующий' : 'Создать новый'}
                    </span>
                  </label>
                ))}
              </div>

              {projectMode === 'existing' && (
                <select
                  value={selectedProjectId}
                  onChange={(e) => setSelectedProjectId(e.target.value)}
                  style={{
                    marginTop: '12px',
                    width: '100%',
                    padding: '10px 12px',
                    border: '1px solid #e2e8f0',
                    borderRadius: '8px',
                    fontSize: '14px',
                    backgroundColor: '#fff',
                  }}
                >
                  <option value="">— Выберите проект —</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
              )}

              {projectMode === 'new' && (
                <input
                  type="text"
                  placeholder="Название нового проекта"
                  value={newProjectName}
                  onChange={(e) => setNewProjectName(e.target.value)}
                  style={{
                    marginTop: '12px',
                    width: '100%',
                    padding: '10px 12px',
                    border: '1px solid #e2e8f0',
                    borderRadius: '8px',
                    fontSize: '14px',
                    boxSizing: 'border-box',
                  }}
                />
              )}
            </div>

            {/* Submit error */}
            {error && (
              <div
                style={{
                  padding: '10px 14px',
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: '8px',
                  marginBottom: '16px',
                  fontSize: '14px',
                  color: '#dc2626',
                }}
              >
                {error}
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={submitting}
              style={{
                width: '100%',
                padding: '13px',
                fontSize: '16px',
                fontWeight: 600,
                backgroundColor: submitting ? '#3b82f6' : '#2563eb',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                cursor: submitting ? 'not-allowed' : 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '10px',
              }}
            >
              {submitting && (
                <span
                  style={{
                    width: '18px',
                    height: '18px',
                    border: '2.5px solid rgba(255,255,255,0.4)',
                    borderTopColor: '#ffffff',
                    borderRadius: '50%',
                    display: 'inline-block',
                    animation: 'spin 0.8s linear infinite',
                    flexShrink: 0,
                  }}
                />
              )}
              {submitting
                ? submitStep === 'upload'
                  ? `Загрузка файлов... ${uploadPercent}%`
                  : 'Создание задачи...'
                : 'Создать задачу'}
            </button>

            {/* Upload progress bar */}
            {submitting && (
              <div style={{ marginTop: '12px' }}>
                <div
                  style={{
                    height: '6px',
                    backgroundColor: '#e2e8f0',
                    borderRadius: '4px',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: submitStep === 'create' ? '100%' : `${uploadPercent}%`,
                      backgroundColor: submitStep === 'create' ? '#22c55e' : '#3b82f6',
                      borderRadius: '4px',
                      transition: 'width 0.2s ease, background-color 0.3s',
                    }}
                  />
                </div>
                <div style={{ marginTop: '6px', fontSize: '12px', color: '#64748b', textAlign: 'center' }}>
                  {submitStep === 'upload'
                    ? `Загрузка ${files.length > 1 ? `${files.length} файлов` : 'файла'}...`
                    : '✓ Файлы загружены — создаём задачу...'}
                </div>
              </div>
            )}

            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
          </form>
        </div>
      </div>
    </Layout>
  );
};

export default TaskCreate;
