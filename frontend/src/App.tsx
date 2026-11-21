import { lazy, Suspense, type ReactElement } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'
import { AuthProvider } from '@/context/AuthProvider'
import { useAuth } from '@/context/authContext'
import { ToastProvider } from '@/context/ToastProvider'
import { ErrorBoundary } from '@/components/common/ErrorBoundary'
import { Layout } from '@/components/layout/Layout'
import { Login } from '@/pages/Login'
import { NotFound } from '@/pages/NotFound'

const Dashboard = lazy(() => import('@/pages/Dashboard').then((m) => ({ default: m.Dashboard })))
const FilesPage = lazy(() => import('@/pages/Files').then((m) => ({ default: m.FilesPage })))
const Predictions = lazy(() => import('@/pages/Predictions').then((m) => ({ default: m.Predictions })))
const ProtectedFiles = lazy(() => import('@/pages/ProtectedFiles').then((m) => ({ default: m.ProtectedFiles })))
const Analytics = lazy(() => import('@/pages/Analytics').then((m) => ({ default: m.Analytics })))
const Security = lazy(() => import('@/pages/Security').then((m) => ({ default: m.Security })))
const Budget = lazy(() => import('@/pages/Budget').then((m) => ({ default: m.Budget })))
const Settings = lazy(() => import('@/pages/Settings').then((m) => ({ default: m.Settings })))

function FullScreenSpinner() {
  return (
    <div role="status" aria-label="Loading" className="flex h-screen items-center justify-center bg-surface">
      <Loader2 className="h-5 w-5 animate-spin text-slate-400" aria-hidden="true" />
    </div>
  )
}

export function RequireAuth({ children }: { children: ReactElement }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <FullScreenSpinner />
  if (status === 'unauthenticated') {
    // Remember where the user was heading so login can send them back.
    return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  }
  return children
}

export function AppRoutes() {
  return (
    <Suspense fallback={<FullScreenSpinner />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/files" element={<FilesPage />} />
          <Route path="/predictions" element={<Predictions />} />
          <Route path="/protected" element={<ProtectedFiles />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/security" element={<Security />} />
          <Route path="/budget" element={<Budget />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <ToastProvider>
          <BrowserRouter>
            <AppRoutes />
          </BrowserRouter>
        </ToastProvider>
      </AuthProvider>
    </ErrorBoundary>
  )
}
