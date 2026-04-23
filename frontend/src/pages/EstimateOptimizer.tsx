import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import Layout from '../components/Layout';
import { getVersions } from '../api/estimateVersions';
import { EstimateVersionSummary } from '../types';

const EstimateOptimizer: React.FC = () => {
  const { taskId } = useParams<{ taskId: string }>();
  const [versions, setVersions] = useState<EstimateVersionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!taskId) return;
    setLoading(true);
    getVersions(taskId)
      .then(setVersions)
      .catch(() => setError('Не удалось загрузить версии сметы'))
      .finally(() => setLoading(false));
  }, [taskId]);

  return (
    <Layout>
      <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
        <div style={{ marginBottom: '24px' }}>
          <h2 style={{ margin: 0, fontSize: '24px', fontWeight: 700, color: '#0f172a' }}>
            Редактор оптимизации сметы
          </h2>
          <p style={{ margin: '6px 0 0', color: '#64748b', fontSize: '14px' }}>
            Задача: {taskId}
          </p>
        </div>

        {loading && (
          <div style={{ color: '#64748b', fontSize: '15px' }}>Загрузка сметы...</div>
        )}

        {error && (
          <div
            style={{
              padding: '12px 16px',
              backgroundColor: '#fef2f2',
              border: '1px solid #fecaca',
              borderRadius: '8px',
              color: '#dc2626',
              fontSize: '14px',
            }}
          >
            {error}
          </div>
        )}

        {!loading && !error && versions.length === 0 && (
          <div
            style={{
              padding: '16px',
              backgroundColor: '#fef9c3',
              border: '1px solid #fde047',
              borderRadius: '8px',
              color: '#854d0e',
              fontSize: '14px',
            }}
          >
            Смета ещё обрабатывается. Обновите страницу через несколько секунд.
          </div>
        )}

        {!loading && versions.length > 0 && (
          <div
            style={{
              padding: '20px',
              backgroundColor: '#f0fdf4',
              border: '1px solid #86efac',
              borderRadius: '10px',
              color: '#166534',
              fontSize: '14px',
            }}
          >
            <strong>Готово!</strong> Загружено {versions.length}{' '}
            {versions.length === 1 ? 'версия' : 'версии'} сметы.
            <ul style={{ margin: '10px 0 0', paddingLeft: '20px' }}>
              {versions.map((v) => (
                <li key={v.id}>
                  {v.version_display_name} ({v.version_label})
                </li>
              ))}
            </ul>
            <p style={{ margin: '12px 0 0', color: '#15803d' }}>
              Полный редактор будет реализован в Фазе 4 (EstimateGrid, VersionTabs, OptimizationToolbar).
            </p>
          </div>
        )}
      </div>
    </Layout>
  );
};

export default EstimateOptimizer;
