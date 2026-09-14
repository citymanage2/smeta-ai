import React from 'react';
import Layout from '../components/Layout';

/**
 * «Мои задачи КП» — рабочее место отдела производства работ.
 *
 * План: plans/2026-09-14-zapros-kp.md. Фаза 1 даёт только адрес и приземление
 * для ролей производства; список запросов, вкладки и счётчик — фаза 5.
 */
const KpInbox: React.FC = () => (
  <Layout>
    <div style={{ maxWidth: 720 }}>
      <h1 style={{ fontSize: 20, fontWeight: 600, color: '#1e293b', margin: '0 0 8px' }}>
        Мои задачи КП
      </h1>
      <div
        style={{
          background: '#ffffff',
          border: '1px solid #e2e8f0',
          borderRadius: 8,
          padding: 16,
          color: '#64748b',
          fontSize: 14,
        }}
      >
        Запросов пока нет. Здесь появятся запросы КП, адресованные вашему отделу.
      </div>
    </div>
  </Layout>
);

export default KpInbox;
