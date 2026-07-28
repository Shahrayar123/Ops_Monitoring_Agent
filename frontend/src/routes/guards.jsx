import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { Spinner } from '../components/ui'

function FullscreenLoader() {
  return (
    <div className="grid min-h-screen place-items-center" style={{ color: 'var(--brand-600)' }}>
      <Spinner className="h-8 w-8 text-brand-600" />
    </div>
  )
}

// Requires a logged-in user; bounces to /login otherwise (remembering where you
// were headed so login can send you back).
export function ProtectedRoute({ children }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <FullscreenLoader />
  if (!user) return <Navigate to="/login" replace state={{ from: location }} />
  return children
}

// Admin-only screens; logged-in non-admins get sent to the dashboard.
export function AdminRoute({ children }) {
  const { user, loading, isAdmin } = useAuth()
  if (loading) return <FullscreenLoader />
  if (!user) return <Navigate to="/login" replace />
  if (!isAdmin) return <Navigate to="/dashboard" replace />
  return children
}

// Keeps logged-in users away from /login and /register.
export function PublicOnlyRoute({ children }) {
  const { user, loading } = useAuth()
  if (loading) return <FullscreenLoader />
  if (user) return <Navigate to="/dashboard" replace />
  return children
}
