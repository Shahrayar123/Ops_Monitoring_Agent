import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Card, Input, PageHeader, Spinner } from '../components/ui'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'
import { authApi } from '../lib/authApi'
import { llmApi } from '../lib/llmApi'
import { monitoringApi } from '../lib/monitoringApi'
import { normalizeError } from '../lib/api'
import { UsageMeter } from '../components/settings/UsageMeter'
import { ApiKeyCard } from '../components/settings/ApiKeyCard'
import { ModelPriority } from '../components/settings/ModelPriority'
import { KpiRefreshSettings } from '../components/settings/KpiRefreshSettings'

export default function Settings() {
  const { user } = useAuth()
  const [llm, setLlm] = useState(null)
  const q = useQuery({
    queryKey: ['llm-settings'],
    queryFn: async () => {
      const s = await llmApi.getSettings()
      setLlm(s)
      return s
    },
  })
  const settings = llm || q.data
  // The refresh-rate section only makes sense once a cluster is assigned —
  // there'd otherwise be nothing for it to apply to.
  const tenantsQ = useQuery({ queryKey: ['tenants'], queryFn: monitoringApi.listTenants })

  return (
    <>
      <PageHeader title="Settings" subtitle="Your profile, AI model, and API keys." />

      <div className="grid gap-6 lg:grid-cols-2">
        <ProfileCard user={user} />
        <PasswordCard />
      </div>

      {user?.role !== 'admin' && <DangerZoneCard />}

      {tenantsQ.data?.length > 0 && (
        <Card className="mt-6">
          <h3 className="mb-1 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>KPI refresh time</h3>
          <p className="mb-4 text-xs" style={{ color: 'var(--muted)' }}>
            How often each dashboard card checks for fresh data. Applies across every cluster you can see.
          </p>
          <KpiRefreshSettings />
        </Card>
      )}

      {q.isLoading || !settings ? (
        <Card className="mt-6"><Spinner /></Card>
      ) : (
        <>
          <Card className="mt-6">
            <h3 className="mb-4 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>AI model priority</h3>
            <ModelPriority settings={settings} onChange={setLlm} />
          </Card>
          <KeysCard settings={settings} onChange={setLlm} />
          <Card className="mt-6">
            <h3 className="mb-4 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>AI usage</h3>
            <UsageMeter usage={settings.usage} />
          </Card>
        </>
      )}
    </>
  )
}

function KeysCard({ settings, onChange }) {
  const toast = useToast()
  const [ollamaUrl, setOllamaUrl] = useState(settings.ollama_base_url)
  const [savingUrl, setSavingUrl] = useState(false)

  async function saveOllama() {
    setSavingUrl(true)
    try {
      onChange(await llmApi.setOllamaUrl(ollamaUrl))
      toast.success('Ollama URL saved.')
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setSavingUrl(false)
    }
  }

  return (
    <Card className="mt-6">
      <h3 className="mb-1 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Provider API keys</h3>
      <p className="mb-4 text-xs" style={{ color: 'var(--muted)' }}>
        Keys are encrypted at rest and never shown again after saving. Bring your own for cloud models.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {settings.providers.map((p) => (
          <ApiKeyCard key={p.provider} provider={p} onChange={onChange} />
        ))}
      </div>

      <div className="mt-5 border-t pt-4" style={{ borderColor: 'var(--line)' }}>
        <div className="flex items-end gap-2">
          <div className="flex-1">
            <Input
              label="Ollama base URL (for local models)"
              hint="Where your Ollama runs — defaults to localhost. Cloud models ignore this."
              value={ollamaUrl}
              onChange={(e) => setOllamaUrl(e.target.value)}
            />
          </div>
          <Button onClick={saveOllama} loading={savingUrl}>Save</Button>
        </div>
      </div>
    </Card>
  )
}

function ProfileCard({ user }) {
  const rows = [['Name', user?.full_name || '—'], ['Email', user?.email], ['Role', user?.role], ['Plan', user?.plan?.name || '—']]
  return (
    <Card>
      <h3 className="mb-4 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Profile</h3>
      <div className="space-y-3 text-sm">
        {rows.map(([k, v]) => (
          <div key={k} className="flex items-center justify-between border-b pb-2 last:border-0" style={{ borderColor: 'var(--line)' }}>
            <span style={{ color: 'var(--faint)' }}>{k}</span>
            <span className="font-medium" style={{ color: 'var(--ink)' }}>{v}</span>
          </div>
        ))}
      </div>
    </Card>
  )
}

function DangerZoneCard() {
  const toast = useToast()
  const { user, setUser } = useAuth()
  const [busy, setBusy] = useState(false)
  const requested = !!user?.deletion_requested_at

  async function requestDeletion() {
    if (!confirm('Request deletion of your account? An admin will review this and permanently delete your account. You can cancel the request any time before that happens.')) return
    setBusy(true)
    try {
      setUser(await authApi.requestDeletion())
      toast.success('Deletion requested — an admin will review it.')
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  async function cancelRequest() {
    setBusy(true)
    try {
      setUser(await authApi.cancelDeletionRequest())
      toast.success('Deletion request cancelled.')
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="mt-6">
      <h3 className="mb-1 text-sm font-bold uppercase tracking-wide text-red-500">Danger zone</h3>
      {requested ? (
        <>
          <p className="mb-4 text-xs" style={{ color: 'var(--muted)' }}>
            Deletion requested on {new Date(user.deletion_requested_at).toLocaleString()}. An admin will review and delete your account — you can still cancel until then.
          </p>
          <Button variant="subtle" onClick={cancelRequest} loading={busy}>Cancel deletion request</Button>
        </>
      ) : (
        <>
          <p className="mb-4 text-xs" style={{ color: 'var(--muted)' }}>
            Deleting your account is permanent. For review, this goes through an admin — request it here and an admin will complete the deletion.
          </p>
          <Button variant="danger" onClick={requestDeletion} loading={busy}>Request account deletion</Button>
        </>
      )}
    </Card>
  )
}

function PasswordCard() {
  const toast = useToast()
  const [pw, setPw] = useState({ current_password: '', new_password: '', confirm: '' })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setPw((p) => ({ ...p, [k]: e.target.value }))

  async function change(e) {
    e.preventDefault()
    if (pw.new_password !== pw.confirm) return toast.error('New passwords do not match.')
    if (pw.new_password.length < 8) return toast.error('Password must be at least 8 characters.')
    setBusy(true)
    try {
      await authApi.changePassword(pw.current_password, pw.new_password)
      toast.success('Password updated.')
      setPw({ current_password: '', new_password: '', confirm: '' })
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h3 className="mb-4 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Change password</h3>
      <form onSubmit={change} className="space-y-4">
        <Input label="Current password" type="password" value={pw.current_password} onChange={set('current_password')} required />
        <Input label="New password" type="password" value={pw.new_password} onChange={set('new_password')} required />
        <Input label="Confirm new password" type="password" value={pw.confirm} onChange={set('confirm')} required />
        <Button type="submit" loading={busy}>Update password</Button>
      </form>
    </Card>
  )
}
