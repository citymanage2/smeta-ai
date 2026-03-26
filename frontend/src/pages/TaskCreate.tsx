import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import TaskTypeSelector from '../components/TaskTypeSelector';
import FileUpload from '../components/FileUpload';
import { TaskType, ProjectCard } from '../types';
import { createTask } from '../api/tasks';
import { listProjects } from '../api/projects';

const TaskCreate: React.FC = () => {
  const navigate = useNavigate();
  const [taskType, setTaskType] = useState<TaskType>('LIST_FROM_TZ');
  const [files, setFiles] = useState<File[]>([]);
  const [prompt, setPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [uploadPercent, setUploadPercent] = useState(0);
  const [submitStep, setSubmitStep] = useState<'upload' | 'create' | null>(null);
  const [error, setError] = useState('');
  const [projects, setProjects] = useState<ProjectCard[]>([]);
  const [projectMode, setProjectMode] = useState<'none' | 'existing' | 'new'>('none');
  const [selectedProjectId, setSelectedProjectId] = useState('');
  const [newProjectName, setNewProjectName] = useState('');

  useEffect(() => {
    listProjects().then(setProjects).catch(() => {});
  }, []);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (files.length === 0) {
      setError('Добавьте хотя бы один файл для обработки.');
      return;
    }

    setSubmitting(true);
    setUploadPercent(0);
    setSubmitStep('upload');

    try {
      const formData = new FormData();
      formData.append('task_type', taskType);
      if (prompt.trim()) {
        formData.append('prompt', prompt.trim());
      }
      files.forEach((file) => {
        formData.append('files', file);
      });

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
      navigate(`/task/${task.task_id}/status`);
    } catch (err: unknown) {
      const axiosError = err as { response?: { data?: { detail?: string } } };
      setError(axiosError.response?.data?.detail ?? 'Ошибка при создании задачи. Попробуйте ещё раз.');
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
            {/* Error */}
            {error && (
              <div
                style={{
                  padding: '10px 14px',
                  backgroundColor: '#fef2f2',
                  border: '1px solid #fecaca',
                  borderRadius: '8px',
                  marginBottom: '20px',
                  fontSize: '14px',
                  color: '#dc2626',
                }}
              >
                {error}
              </div>
            )}

            {/* Task type */}
            <div style={{ marginBottom: '24px' }}>
              <TaskTypeSelector value={taskType} onChange={setTaskType} disabled={submitting} />
            </div>

            {/* File upload */}
            <div style={{ marginBottom: '24px' }}>
              <FileUpload files={files} onChange={setFiles} />
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
