import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/auth';
import ProjectsSidebar from './ProjectsSidebar';

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const navigate = useNavigate();
  const { role, logout, isAdmin, isAuthenticated } = useAuthStore();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div style={{ height: '100vh', backgroundColor: '#f8fafc', display: 'flex', flexDirection: 'column' }}>

      {/* ── Header ── */}
      <header
        style={{
          backgroundColor: '#ffffff',
          borderBottom: '1px solid #e2e8f0',
          padding: '0 24px',
          height: '64px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          zIndex: 100,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span
            style={{
              fontSize: '22px',
              fontWeight: 700,
              color: '#2563eb',
              cursor: 'pointer',
              letterSpacing: '-0.5px',
            }}
            onClick={() => navigate(isAdmin ? '/admin' : '/task/create')}
          >
            Smeta AI
          </span>
          <span
            style={{
              fontSize: '11px',
              fontWeight: 600,
              backgroundColor: isAdmin ? '#7c3aed' : '#2563eb',
              color: '#ffffff',
              padding: '2px 8px',
              borderRadius: '12px',
              letterSpacing: '0.5px',
              textTransform: 'uppercase',
            }}
          >
            {role === 'admin' ? 'Администратор' : 'Пользователь'}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {isAdmin && (
            <button
              onClick={() => navigate('/admin')}
              style={{
                padding: '7px 16px',
                backgroundColor: 'transparent',
                color: '#64748b',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              Панель администратора
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => navigate('/task/create')}
              style={{
                padding: '7px 16px',
                backgroundColor: 'transparent',
                color: '#64748b',
                border: '1px solid #e2e8f0',
                borderRadius: '8px',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              Создать задачу
            </button>
          )}
          <button
            onClick={() => navigate('/projects')}
            style={{
              padding: '7px 16px',
              backgroundColor: 'transparent',
              color: '#64748b',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 500,
            }}
          >
            Проекты
          </button>
          <button
            onClick={() => navigate('/calculator')}
            style={{
              padding: '7px 16px',
              backgroundColor: 'transparent',
              color: '#64748b',
              border: '1px solid #e2e8f0',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 500,
            }}
          >
            Калькулятор
          </button>
          <button
            onClick={handleLogout}
            style={{
              padding: '7px 16px',
              backgroundColor: '#fee2e2',
              color: '#dc2626',
              border: 'none',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '14px',
              fontWeight: 500,
            }}
          >
            Выйти
          </button>
        </div>
      </header>

      {/* ── Body: sidebar + content ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Projects sidebar — visible for all authenticated users */}
        {isAuthenticated && <ProjectsSidebar />}

        {/* Main content + footer */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          <main
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: '32px 24px',
              boxSizing: 'border-box',
            }}
          >
            {children}
          </main>

          <footer
            style={{
              borderTop: '1px solid #e2e8f0',
              padding: '14px 24px',
              textAlign: 'center',
              color: '#94a3b8',
              fontSize: '13px',
              backgroundColor: '#ffffff',
              flexShrink: 0,
            }}
          >
            © {new Date().getFullYear()} Smeta AI — Автоматизация строительных смет
          </footer>
        </div>
      </div>

    </div>
  );
};

export default Layout;
