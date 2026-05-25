import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import ErrorBoundary from './components/ErrorBoundary';
import Login from './pages/Login';
import TaskCreate from './pages/TaskCreate';
import TaskStatus from './pages/TaskStatus';
import EstimateOptimizer from './pages/EstimateOptimizer';
import Admin from './pages/Admin';
import Projects from './pages/Projects';
import ProjectDetail from './pages/ProjectDetail';
import ProjectCardPage from './pages/ProjectCardPage';
import UnassignedTasks from './pages/UnassignedTasks';
import Calculator from './pages/Calculator';
import Trash from './pages/Trash';
import PriceCatalog from './pages/PriceCatalog';
import System from './pages/System';
import SummaryEditor from './pages/SummaryEditor';
import Retraining from './pages/Retraining';
import { useAuthStore } from './stores/auth';

const App: React.FC = () => {
  const { isAuthenticated } = useAuthStore();

  return (
    <BrowserRouter>
      <Routes>
        {/* Public route */}
        <Route
          path="/login"
          element={
            isAuthenticated ? (
              <Navigate to="/system" replace />
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
          path="/tasks/:taskId/status"
          element={
            <ProtectedRoute>
              <TaskStatus />
            </ProtectedRoute>
          }
        />
        <Route
          path="/tasks/:taskId/estimate"
          element={
            <ProtectedRoute>
              <ErrorBoundary>
                <EstimateOptimizer />
              </ErrorBoundary>
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects"
          element={
            <ProtectedRoute>
              <Projects />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/unassigned"
          element={
            <ProtectedRoute>
              <UnassignedTasks />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:projectId"
          element={
            <ProtectedRoute>
              <ProjectDetail />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:projectId/cards/:cardId"
          element={
            <ProtectedRoute>
              <ProjectCardPage />
            </ProtectedRoute>
          }
        />
        <Route
          path="/projects/:projectId/summary"
          element={
            <ProtectedRoute>
              <ErrorBoundary>
                <SummaryEditor />
              </ErrorBoundary>
            </ProtectedRoute>
          }
        />
        <Route
          path="/calculator"
          element={
            <ProtectedRoute>
              <Calculator />
            </ProtectedRoute>
          }
        />
        <Route
          path="/trash"
          element={
            <ProtectedRoute>
              <Trash />
            </ProtectedRoute>
          }
        />
        <Route
          path="/catalog"
          element={
            <ProtectedRoute>
              <PriceCatalog />
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
        <Route
          path="/retraining"
          element={
            <ProtectedRoute requireAdmin>
              <Retraining />
            </ProtectedRoute>
          }
        />

        {/* System dashboard */}
        <Route
          path="/system"
          element={
            <ProtectedRoute>
              <System />
            </ProtectedRoute>
          }
        />

        {/* Default redirect */}
        <Route
          path="/"
          element={
            <Navigate
              to={isAuthenticated ? '/system' : '/login'}
              replace
            />
          }
        />

        {/* Catch-all redirect */}
        <Route
          path="*"
          element={
            <Navigate
              to={isAuthenticated ? '/system' : '/login'}
              replace
            />
          }
        />
      </Routes>
    </BrowserRouter>
  );
};

export default App;
