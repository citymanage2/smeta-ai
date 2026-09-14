import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/auth';
import { KP_INBOX_PATH } from '../utils/roles';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
  requireManager?: boolean;
  // Отделу производства работ по умолчанию закрыт любой экран — как и API на
  // сервере. Открывается явно, только для экранов запросов КП.
  allowProduction?: boolean;
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requireAdmin = false,
  requireManager = false,
  allowProduction = false,
}) => {
  const { isAuthenticated, isAdmin, isManager, isProduction } = useAuthStore();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (isProduction && !allowProduction) {
    return <Navigate to={KP_INBOX_PATH} replace />;
  }

  if (requireAdmin && !isAdmin) {
    return <Navigate to="/projects" replace />;
  }

  if (requireManager && !isManager) {
    return <Navigate to="/projects" replace />;
  }

  return <>{children}</>;
};

export default ProtectedRoute;
