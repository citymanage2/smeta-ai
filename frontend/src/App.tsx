import React, { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import ProtectedRoute from './components/ProtectedRoute';
import ErrorBoundary from './components/ErrorBoundary';
import Login from './pages/Login';
import { useAuthStore } from './stores/auth';

// Ленивая загрузка страниц по роутам: тяжёлые библиотеки (recharts на /system,
// xlsx-редакторы на /tasks/:id/estimate) грузятся только при переходе на экран,
// а не в первичном бандле логина. Login оставлен eager — это первый paint.
const TaskCreate = lazy(() => import('./pages/TaskCreate'));
const TaskStatus = lazy(() => import('./pages/TaskStatus'));
const EstimateOptimizer = lazy(() => import('./pages/EstimateOptimizer'));
const Admin = lazy(() => import('./pages/Admin'));
const Projects = lazy(() => import('./pages/Projects'));
const Archive = lazy(() => import('./pages/Archive'));
const ProjectDetail = lazy(() => import('./pages/ProjectDetail'));
const ProjectCardPage = lazy(() => import('./pages/ProjectCardPage'));
const DocumentPage = lazy(() => import('./pages/DocumentPage'));
const Calculator = lazy(() => import('./pages/Calculator'));
const Trash = lazy(() => import('./pages/Trash'));
const PriceCatalog = lazy(() => import('./pages/PriceCatalog'));
const System = lazy(() => import('./pages/System'));
const SummaryEditor = lazy(() => import('./pages/SummaryEditor'));
const Retraining = lazy(() => import('./pages/Retraining'));
const Corrections = lazy(() => import('./pages/Corrections'));
const Employees = lazy(() => import('./pages/Employees'));

const RouteFallback: React.FC = () => (
  <div style={{ padding: 32, textAlign: 'center', color: '#64748b' }}>Загрузка…</div>
);

const App: React.FC = () => {
  const { isAuthenticated } = useAuthStore();

  // Приземление после логина: «Входящий» (/system) для всех ролей.
  const landingPath = '/system';

  return (
    <BrowserRouter>
      <Suspense fallback={<RouteFallback />}>
      <Routes>
        {/* Public route */}
        <Route
          path="/login"
          element={
            isAuthenticated ? (
              <Navigate to={landingPath} replace />
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
          path="/archive"
          element={
            <ProtectedRoute>
              <Archive />
            </ProtectedRoute>
          }
        />
        {/* «Задачи без проекта» поглощены «Входящим» (/system) */}
        <Route path="/projects/unassigned" element={<Navigate to={landingPath} replace />} />
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
        {/* Документ страницей, а не окном поверх экрана: у таблицы есть адрес,
            и «Назад» закрывает её, а не уводит с экрана. */}
        <Route
          path="/projects/:projectId/cards/:cardId/document/:kind"
          element={
            <ProtectedRoute>
              <ErrorBoundary>
                <DocumentPage />
              </ErrorBoundary>
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
        <Route
          path="/corrections"
          element={
            <ProtectedRoute requireManager>
              <Corrections />
            </ProtectedRoute>
          }
        />
        <Route
          path="/employees"
          element={
            <ProtectedRoute requireAdmin>
              <Employees />
            </ProtectedRoute>
          }
        />

        {/* «Входящий» — домашняя для всех ролей (виджеты дашборда внутри — только менеджеру) */}
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
              to={isAuthenticated ? landingPath : '/login'}
              replace
            />
          }
        />

        {/* Catch-all redirect */}
        <Route
          path="*"
          element={
            <Navigate
              to={isAuthenticated ? landingPath : '/login'}
              replace
            />
          }
        />
      </Routes>
      </Suspense>
    </BrowserRouter>
  );
};

export default App;
