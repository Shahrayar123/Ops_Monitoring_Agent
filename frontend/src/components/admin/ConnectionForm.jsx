import { useState } from 'react'
import { Button, Input } from '../ui'
import { tenantAdminApi } from '../../lib/tenantAdminApi'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'

// Live Cloudera Manager connection: fill in host/port/credentials, TEST before
// saving, then save (password encrypted at rest on the backend).
export function ConnectionForm({ tenant, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState({
    cm_host: tenant.cm_host || '',
    cm_port: tenant.cm_port || 7183,
    cm_use_tls: tenant.cm_use_tls ?? true,
    cm_username: tenant.cm_username || '',
    cm_password: '',
  })
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState(false)
  const [saving, setSaving] = useState(false)

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))
  const payload = () => ({
    ...form,
    cm_port: Number(form.cm_port),
    cm_password: form.cm_password || undefined,
  })

  async function test() {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await tenantAdminApi.testConnection(tenant.slug, payload())
      setTestResult(r)
    } catch (err) {
      setTestResult({ ok: false, message: normalizeError(err).message })
    } finally {
      setTesting(false)
    }
  }

  async function save() {
    setSaving(true)
    try {
      const updated = await tenantAdminApi.setConnection(tenant.slug, payload())
      toast.success('Connection saved.')
      onSaved(updated)
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label="CM host" placeholder="cm.cluster.internal" value={form.cm_host} onChange={set('cm_host')} />
        <Input label="Port" type="number" value={form.cm_port} onChange={set('cm_port')} />
        <Input label="Username" value={form.cm_username} onChange={set('cm_username')} />
        <Input
          label="Password"
          type="password"
          placeholder={tenant.has_cm_password ? '•••••••• (unchanged)' : 'Cloudera Manager password'}
          value={form.cm_password}
          onChange={set('cm_password')}
          hint={tenant.has_cm_password ? 'Leave blank to keep the stored password' : undefined}
        />
      </div>
      <label className="flex items-center gap-2 text-sm" style={{ color: 'var(--ink)' }}>
        <input type="checkbox" checked={form.cm_use_tls} onChange={(e) => setForm((f) => ({ ...f, cm_use_tls: e.target.checked }))} />
        Use TLS (https)
      </label>

      {testResult && (
        <div
          className="rounded-xl px-4 py-2.5 text-sm font-medium"
          style={{
            background: testResult.ok ? 'rgba(34,197,94,0.1)' : 'rgba(239,68,68,0.1)',
            color: testResult.ok ? '#15803d' : '#b91c1c',
          }}
        >
          {testResult.ok ? '✅ ' : '⚠️ '}
          {testResult.message}
        </div>
      )}

      <div className="flex gap-3">
        <Button variant="subtle" onClick={test} loading={testing}>Test connection</Button>
        <Button onClick={save} loading={saving}>Save connection</Button>
      </div>
    </div>
  )
}
