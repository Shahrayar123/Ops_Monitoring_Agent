import { useState } from 'react'
import { Button, Input } from './ui'
import { authApi } from '../lib/authApi'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { normalizeError } from '../lib/api'

// Blocking modal for invited users: they must set their own password before
// using the app. Shown whenever the logged-in user has must_change_password.
export function ForcePasswordChange() {
  const { user, setUser } = useAuth()
  const toast = useToast()
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setPw((p) => ({ ...p, [k]: e.target.value }))

  if (!user?.must_change_password) return null

  async function submit(e) {
    e.preventDefault()
    if (pw.new_password !== pw.confirm) return toast.error('Passwords do not match.')
    if (pw.new_password.length < 8) return toast.error('Password must be at least 8 characters.')
    setBusy(true)
    try {
      await authApi.changePassword(pw.current_password, pw.new_password)
      setUser({ ...user, must_change_password: false })
      toast.success('Password set — welcome!')
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[90] grid place-items-center bg-black/60 p-4">
      <div className="card w-full max-w-sm p-6 animate-fade-in">
        <h3 className="text-lg font-bold" style={{ color: 'var(--ink)' }}>Set your password</h3>
        <p className="mt-1 mb-4 text-sm" style={{ color: 'var(--muted)' }}>
          Your account was created by an administrator. Choose your own password to continue.
        </p>
        <form onSubmit={submit} className="space-y-3">
          <Input label="Temporary password" type="password" value={pw.current_password} onChange={set('current_password')} required />
          <Input label="New password" type="password" value={pw.new_password} onChange={set('new_password')} required />
          <Input label="Confirm new password" type="password" value={pw.confirm} onChange={set('confirm')} required />
          <Button type="submit" loading={busy} className="w-full">Set password</Button>
        </form>
      </div>
    </div>
  )
}
