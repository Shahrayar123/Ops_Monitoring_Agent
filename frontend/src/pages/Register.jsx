import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AuthLayout } from './AuthLayout'
import { Button, Input } from '../components/ui'
import { authApi } from '../lib/authApi'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { normalizeError } from '../lib/api'

export default function Register() {
  const { login } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()

  const [form, setForm] = useState({ full_name: '', email: '', password: '', confirm: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    if (form.password !== form.confirm) return setError('Passwords do not match.')
    if (form.password.length < 8) return setError('Password must be at least 8 characters.')
    setBusy(true)
    try {
      await authApi.register(form)
      await login(form.email, form.password) // auto sign-in after registering
      toast.success('Account created — welcome!')
      navigate('/dashboard', { replace: true })
    } catch (err) {
      setError(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthLayout>
      <h2 className="text-2xl font-bold tracking-tight" style={{ color: 'var(--ink)' }}>
        Create your account
      </h2>
      <p className="mt-1 text-sm" style={{ color: 'var(--muted)' }}>
        Start monitoring your Cloudera clusters in minutes.
      </p>

      <form onSubmit={onSubmit} className="mt-6 space-y-4">
        <Input label="Full name" placeholder="Jane Operator" value={form.full_name} onChange={set('full_name')} />
        <Input
          label="Email"
          type="email"
          autoComplete="username"
          placeholder="you@company.com"
          value={form.email}
          onChange={set('email')}
          required
        />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          placeholder="At least 8 characters"
          value={form.password}
          onChange={set('password')}
          required
        />
        <Input
          label="Confirm password"
          type="password"
          autoComplete="new-password"
          placeholder="Re-enter password"
          value={form.confirm}
          onChange={set('confirm')}
          required
        />
        {error && <p className="text-sm text-red-500">{error}</p>}
        <Button type="submit" loading={busy} className="w-full">
          Create account
        </Button>
      </form>

      <p className="mt-6 text-center text-sm" style={{ color: 'var(--muted)' }}>
        Already have an account?{' '}
        <Link to="/login" className="font-semibold text-brand-600 hover:underline">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  )
}
