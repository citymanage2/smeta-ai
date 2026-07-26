import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '../stores/auth';

interface ProtectedRouteProps {
  children: React.ReactNode;
  requireAdmin?: boolean;
  requireManager?: boolean;
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  requireAdmin = false,
  requireManager = false,
}) => {
  const { isAuthenticated, isAdmin, isManager } = useAuthStore();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
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
