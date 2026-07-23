import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Card, Input, Spinner } from '../ui'
import { monitoringApi } from '../../lib/monitoringApi'
import { tenantAdminApi } from '../../lib/tenantAdminApi'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'
import { FileUploadManager } from './FileUploadManager'
import { ConnectionForm } from './ConnectionForm'

export function TenantManager() {
  const [selected, setSelected] = useState(null)
  const [creating, setCreating] = useState(false)
  const tenantsQ = useQuery({ queryKey: ['tenants'], queryFn: monitoringApi.listTenants })

  return (
    <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
      {/* Cluster list */}
      <Card className="h-max">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Clusters</h3>
          <button onClick={() => { setCreating(true); setSelected(null) }} className="text-sm font-bold text-brand-600">+ New</button>
        </div>
        {tenantsQ.isLoading ? (
          <Spinner />
        ) : (
          <div className="space-y-1">
            {tenantsQ.data?.map((t) => (
              <button
                key={t.slug}
                onClick={() => { setSelected(t.slug); setCreating(false) }}
                className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition ${
                  selected === t.slug ? 'bg-brand-600 text-white' : 'hover:bg-black/5 dark:hover:bg-white/5'
                }`}
                style={selected === t.slug ? undefined : { color: 'var(--ink)' }}
              >
                <div className="font-semibold">{t.display_name}</div>
                <div className={`text-xs ${selected === t.slug ? 'text-white/70' : ''}`} style={selected === t.slug ? undefined : { color: 'var(--faint)' }}>
                  {t.data_source_mode === 'api' ? '🌐 Live API' : '📄 Files'} · {t.slug}
                </div>
              </button>
            ))}
            {tenantsQ.data?.length === 0 && <p className="text-sm" style={{ color: 'var(--faint)' }}>No clusters yet.</p>}
          </div>
        )}
      </Card>

      {/* Detail / create */}
      <div>
        {creating ? (
          <CreateTenant onCreated={(t) => { tenantsQ.refetch(); setCreating(false); setSelected(t.slug) }} />
        ) : selected ? (
          <TenantDetail slug={selected} onModeChange={() => tenantsQ.refetch()} />
        ) : (
          <Card className="grid place-items-center py-16 text-center">
            <div className="text-4xl">🗂️</div>
            <p className="mt-2 text-sm" style={{ color: 'var(--muted)' }}>Select a cluster or create a new one.</p>
          </Card>
        )}
      </div>
    </div>
  )
}

function CreateTenant({ onCreated }) {
  const toast = useToast()
  const [form, setForm] = useState({ slug: '', display_name: '', cluster_name: '', cloudera_version: '', data_source_mode: 'json' })
  const [busy, setBusy] = useState(false)
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }))

  async function create() {
    setBusy(true)
    try {
      const t = await tenantAdminApi.create(form)
      toast.success(`Cluster '${t.display_name}' created.`)
      onCreated(t)
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card>
      <h3 className="mb-4 text-lg font-bold" style={{ color: 'var(--ink)' }}>New cluster</h3>
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label="Slug" hint="lowercase id, e.g. acme-prod" value={form.slug} onChange={set('slug')} />
        <Input label="Display name" value={form.display_name} onChange={set('display_name')} />
        <Input label="Cluster name" hint="as it appears in Cloudera Manager" value={form.cluster_name} onChange={set('cluster_name')} />
        <Input label="Cloudera version" placeholder="7.1.9" value={form.cloudera_version} onChange={set('cloudera_version')} />
        <label className="block">
          <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>Data source</span>
          <select value={form.data_source_mode} onChange={set('data_source_mode')}
            className="w-full rounded-xl border px-3.5 py-2.5 text-sm" style={{ background: 'var(--surface-2)', borderColor: 'var(--line)', color: 'var(--ink)' }}>
            <option value="json">📄 JSON export files (demo stage)</option>
            <option value="api">🌐 Live Cloudera API</option>
          </select>
        </label>
      </div>
      <div className="mt-5">
        <Button onClick={create} loading={busy}>Create cluster</Button>
      </div>
    </Card>
  )
}

function TenantDetail({ slug, onModeChange }) {
  const toast = useToast()
  const [tenant, setTenant] = useState(null)
  const q = useQuery({
    queryKey: ['tenant-detail', slug],
    queryFn: async () => {
      const t = await monitoringApi.getTenant(slug)
      setTenant(t)
      return t
    },
  })
  const t = tenant || q.data
  if (!t) return <Spinner />

  async function switchMode(mode) {
    try {
      const updated = await tenantAdminApi.update(slug, { data_source_mode: mode })
      setTenant(updated)
      onModeChange?.()
      toast.info(`Switched to ${mode === 'api' ? 'Live API' : 'JSON files'} mode.`)
    } catch (err) {
      toast.error(normalizeError(err).message)
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-lg font-bold" style={{ color: 'var(--ink)' }}>{t.display_name}</h3>
            <p className="text-sm" style={{ color: 'var(--faint)' }}>{t.cluster_name} · {t.slug} · CDP {t.cloudera_version || '—'}</p>
          </div>
          <div className="flex overflow-hidden rounded-xl border" style={{ borderColor: 'var(--line)' }}>
            {[['json', '📄 JSON files'], ['api', '🌐 Live API']].map(([m, label]) => (
              <button
                key={m}
                onClick={() => switchMode(m)}
                className={`px-4 py-2 text-sm font-semibold transition ${t.data_source_mode === m ? 'bg-brand-600 text-white' : ''}`}
                style={t.data_source_mode === m ? undefined : { color: 'var(--muted)' }}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      </Card>

      <Card>
        {t.data_source_mode === 'json' ? (
          <>
            <h4 className="mb-1 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Export files</h4>
            <p className="mb-4 text-xs" style={{ color: 'var(--muted)' }}>
              Upload this cluster's Cloudera Manager export files. Each is validated against the real check parser on upload.
            </p>
            <FileUploadManager tenant={t} onChange={(updated) => setTenant(updated)} />
          </>
        ) : (
          <>
            <h4 className="mb-1 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Live Cloudera Manager connection</h4>
            <p className="mb-4 text-xs" style={{ color: 'var(--muted)' }}>
              Enter the cluster's CM address and credentials. Test before saving; the password is encrypted at rest.
            </p>
            <ConnectionForm tenant={t} onSaved={(updated) => setTenant(updated)} />
          </>
        )}
      </Card>
    </div>
  )
}
