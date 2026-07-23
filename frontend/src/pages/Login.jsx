import { useState } from 'react'
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { AuthLayout } from './AuthLayout'
import { Button, Input } from '../components/ui'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { normalizeError } from '../lib/api'
import { authApi } from '../lib/authApi'

export default function Login() {
  const { login } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const [params] = useSearchParams()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [offerRecovery, setOfferRecovery] = useState(false)
  const [recovering, setRecovering] = useState(false)
  const [recoverySubmitted, setRecoverySubmitted] = useState(false)

  const expired = params.get('expired')

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    setOfferRecovery(false)
    setRecoverySubmitted(false)
    setBusy(true)
    try {
      await login(email, password)
      toast.success('Welcome back!')
      navigate(location.state?.from?.pathname || '/dashboard', { replace: true })
    } catch (err) {
      const n = normalizeError(err)
      setError(n.message)
      setOfferRecovery(n.message.includes('This account has been deleted'))
    } finally {
      setBusy(false)
    }
  }

  async function onRequestRecovery() {
    setRecovering(true)
    try {
      const { message } = await authApi.recoverAccount(email, password)
      toast.success(message)
      setRecoverySubmitted(true)
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setRecovering(false)
    }
  }

  return (
    <AuthLayout>
      <h2 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--ink)' }}>
        Sign in
      </h2>
      <p className="mt-1 text-sm" style={{ color: 'var(--muted)' }}>
        Welcome back — sign in to your monitoring console.
      </p>

      {expired && (
        <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-500/10">
          Your session expired. Please sign in again.
        </div>
      )}

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <Input
          label="Email"
          type="email"
          autoComplete="username"
          placeholder="you@company.com"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
        />
        <Input
          label="Password"
          type="password"
          autoComplete="current-password"
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
        />
        {error && <p className="text-sm text-red-500">{error}</p>}
        {offerRecovery && !recoverySubmitted && (
          <Button type="button" variant="subtle" loading={recovering} onClick={onRequestRecovery} className="w-full">
            Request account recovery
          </Button>
        )}
        {recoverySubmitted && (
          <p className="text-xs" style={{ color: 'var(--muted)' }}>
            Your recovery request has been submitted for admin review.
          </p>
        )}
        <Button type="submit" loading={busy} className="w-full">
          Sign in
        </Button>
      </form>

      <p className="mt-6 text-center text-sm" style={{ color: 'var(--muted)' }}>
        Don't have an account?{' '}
        <Link to="/register" className="font-semibold text-brand-600 hover:underline">
          Create one
        </Link>
      </p>
    </AuthLayout>
  )
}
