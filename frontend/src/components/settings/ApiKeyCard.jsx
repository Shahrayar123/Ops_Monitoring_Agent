import { useState } from 'react'
import { Button, Input } from '../ui'
import { llmApi } from '../../lib/llmApi'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'

// One provider's API-key card. The real key is write-only — after saving, only a
// masked ••••••••abcd ever comes back from the server.
export function ApiKeyCard({ provider, onChange }) {
  const toast = useToast()
  const [value, setValue] = useState('')
  const [editing, setEditing] = useState(!provider.configured)
  const [busy, setBusy] = useState(false)

  async function save() {
    if (value.length < 8) return toast.error('That key looks too short.')
    setBusy(true)
    try {
      const s = await llmApi.setKey(provider.provider, value.trim())
      toast.success(`${provider.provider_label} key saved.`)
      setValue('')
      setEditing(false)
      onChange(s)
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  async function remove() {
    setBusy(true)
    try {
      const s = await llmApi.deleteKey(provider.provider)
      toast.info(`${provider.provider_label} key removed.`)
      setEditing(true)
      onChange(s)
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-xl border p-4" style={{ borderColor: 'var(--line)' }}>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>{provider.provider_label}</span>
        {provider.configured ? (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-bold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">CONFIGURED</span>
        ) : (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold text-slate-500 dark:bg-slate-500/15">NO KEY</span>
        )}
      </div>

      {!editing && provider.configured ? (
        <div className="flex items-center justify-between gap-2">
          <code className="text-sm" style={{ color: 'var(--muted)' }}>{provider.masked_key}</code>
          <div className="flex gap-2">
            <button onClick={() => setEditing(true)} className="text-xs font-semibold text-brand-600">Replace</button>
            <button onClick={remove} disabled={busy} className="text-xs font-semibold text-red-500">Remove</button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          <input
            type="password"
            placeholder={`${provider.provider_label} API key`}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="min-w-0 flex-1 rounded-lg border px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-brand-400/50"
            style={{ background: 'var(--surface-2)', borderColor: 'var(--line)', color: 'var(--ink)' }}
          />
          <Button onClick={save} loading={busy}>Save</Button>
          {provider.configured && <Button variant="subtle" onClick={() => setEditing(false)}>Cancel</Button>}
        </div>
      )}
    </div>
  )
}
