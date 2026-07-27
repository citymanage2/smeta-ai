import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Toaster } from 'sonner';
import { useAuthStore } from '../stores/auth';
import { useGlobalTaskPoller } from '../hooks/useGlobalTaskPoller';
import { ROLE_LABELS } from '../api/adminUsers';
import ProjectsSidebar from './ProjectsSidebar';

interface LayoutProps {
  children: React.ReactNode;
}

const Layout: React.FC<LayoutProps> = ({ children }) => {
  const navigate = useNavigate();
  const { role, logout, isAdmin, isAuthenticated } = useAuthStore();
  useGlobalTaskPoller();

  const roleLabel = (role && ROLE_LABELS[role]) || 'Сотрудник';

  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() => {
    const stored = localStorage.getItem('sidebarOpen');
    return stored === null ? false : stored !== 'false';
  });

  const handleToggleSidebar = () => {
    setSidebarOpen(prev => {
      const next = !prev;
      localStorage.setItem('sidebarOpen', String(next));
      return next;
    });
  };

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
          height: '56px',
          flexShrink: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          boxShadow: '0 1px 3px rgba(0,0,0,0.05)',
          zIndex: 100,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span
            style={{
              fontSize: '20px',
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
              fontSize: '10px',
              fontWeight: 600,
              backgroundColor: isAdmin ? '#7c3aed' : '#2563eb',
              color: '#ffffff',
              padding: '2px 8px',
              borderRadius: '12px',
              letterSpacing: '0.5px',
              textTransform: 'uppercase',
            }}
          >
            {roleLabel}
          </span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {isAdmin && (
            <button
              onClick={() => navigate('/admin')}
              style={headerBtnStyle}
            >
              Администратор
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => navigate('/retraining')}
              style={headerBtnStyle}
            >
              Дообучение
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => navigate('/employees')}
              style={headerBtnStyle}
            >
              Сотрудники
            </button>
          )}
          <button onClick={() => navigate('/task/create')} style={headerBtnStyle}>
            Создать задачу
          </button>
          <button onClick={() => navigate('/projects')} style={headerBtnStyle}>
            Проекты
          </button>
          <button onClick={() => navigate('/calculator')} style={headerBtnStyle}>
            Калькулятор
          </button>
          <button
            onClick={handleLogout}
            style={{
              ...headerBtnStyle,
              backgroundColor: '#fee2e2',
              color: '#dc2626',
              border: 'none',
            }}
          >
            Выйти
          </button>
        </div>
      </header>

      {/* ── Body: sidebar + content ── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
        {isAuthenticated && (
          <ProjectsSidebar open={sidebarOpen} onToggle={handleToggleSidebar} />
        )}

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
              padding: '12px 24px',
              textAlign: 'center',
              color: '#94a3b8',
              fontSize: '12px',
              backgroundColor: '#ffffff',
              flexShrink: 0,
            }}
          >
            © {new Date().getFullYear()} Smeta AI — Автоматизация строительных смет
          </footer>
        </div>
      </div>

      <Toaster position="bottom-right" richColors />
    </div>
  );
};

const headerBtnStyle: React.CSSProperties = {
  padding: '6px 14px',
  backgroundColor: 'transparent',
  color: '#64748b',
  border: '1px solid #e2e8f0',
  borderRadius: '7px',
  cursor: 'pointer',
  fontSize: '13px',
  fontWeight: 500,
};

export default Layout;
