import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import Login from './pages/Login';
import TaskCreate from './pages/TaskCreate';
import TaskStatus from './pages/TaskStatus';
import EstimateView from './pages/EstimateView';
import Admin from './pages/Admin';
import { useAuthStore } from './stores/auth';

const App: React.FC = () => {
  const { isAuthenticated, isAdmin } = useAuthStore();

  return (
    <BrowserRouter>
      <Routes>
        {/* Public route */}
        <Route
          path="/login"
          element={
            isAuthenticated ? (
              <Navigate to={isAdmin ? '/admin' : '/task/create'} replace />
            ) : (
              <Login />
            )
          }
        />

        {/* Protected user routes */}
        <Route
          path="/task/create"
          element={
            <ProtectedRoute>
              <TaskCreate />
            </ProtectedRoute>
          }
        />
        <Route
          path="/task/:taskId/status"
          element={
            <ProtectedRoute>
              <TaskStatus />
            </ProtectedRoute>
          }
        />
        <Route
          path="/task/:taskId/estimate"
          element={
            <ProtectedRoute>
              <EstimateView />
            </ProtectedRoute>
          }
        />

        {/* Protected admin routes */}
        <Route
          path="/admin"
          element={
            <ProtectedRoute requireAdmin>
              <Admin />
            </ProtectedRoute>
          }
        />

        {/* Default redirect */}
        <Route
          path="/"
          element={
            <Navigate
              to={isAuthenticated ? (isAdmin ? '/admin' : '/task/create') : '/login'}
              replace
            />
          }
        />

        {/* Catch-all redirect */}
        <Route
          path="*"
          element={
            <Navigate
              to={isAuthenticated ? (isAdmin ? '/admin' : '/task/create') : '/login'}
              replace
            />
          }
        />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
