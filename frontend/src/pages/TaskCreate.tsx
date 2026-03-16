import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Layout from '../components/Layout';
import TaskTypeSelector from '../components/TaskTypeSelector';
import FileUpload from '../components/FileUpload';
import { TaskType } from '../types';
import { createTask } from '../api/tasks';

const TaskCreate: React.FC = () => {
  const navigate = useNavigate();
  const [taskType, setTaskType] = useState<TaskType>('LIST_FROM_TZ');
  const [files, setFiles] = useState<File[]>([]);
  const [prompt, setPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (files.length === 0) {
      setError('Добавьте хотя бы один файл для обработки.');
      return;
    }

    setSubmitting(true);
    try {
      const formData = new FormData();
      formData.append('task_type', taskType);
      if (prompt.trim()) {
        formData.append('user_prompt', prompt.trim());
      }
      files.forEach((file) => {
        formData.append('files', file);
      });

      const task = await createTask(formData);
      navigate(`/task/${task.id}/status`);
    } catch (err: unknown) {
      const axiosError = err as { response?: { data?: { detail?: string } } };
      setError(axiosError.response?.data?.detail ?? 'Ошибка при создании задачи. Попробуйте ещё раз.');
    } finally {
      setSubmitting(false);
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

            {/* Submit */}
            <button
              type="submit"
              disabled={submitting}
              style={{
                width: '100%',
                padding: '13px',
                fontSize: '16px',
                fontWeight: 600,
                backgroundColor: submitting ? '#93c5fd' : '#2563eb',
                color: '#ffffff',
                border: 'none',
                borderRadius: '8px',
                cursor: submitting ? 'not-allowed' : 'pointer',
                transition: 'background-color 0.15s',
              }}
            >
              {submitting ? 'Создание задачи...' : 'Создать задачу'}
            </button>
          </form>
        </div>
      </div>
    </Layout>
  );
};

export default TaskCreate;
