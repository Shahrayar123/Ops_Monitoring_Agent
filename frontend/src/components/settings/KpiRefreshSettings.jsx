import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Spinner } from '../ui'
import { kpiSettingsApi } from '../../lib/kpiSettingsApi'
import { CHECK_META } from '../../lib/monitoringApi'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'

// How often each KPI card polls for fresh data. Per-user, not per-cluster —
// applies to every cluster this user can see. Only rendered by Settings.jsx
// once the user has at least one assigned cluster (no point configuring
// refresh timing for cards that don't exist yet).
export function KpiRefreshSettings() {
  const toast = useToast()
  const [drafts, setDrafts] = useState({}) // task -> in-progress input value (string)
  const [busyTask, setBusyTask] = useState(null)
  const ratesQ = useQuery({ queryKey: ['kpi-refresh-rates'], queryFn: kpiSettingsApi.list })

  if (ratesQ.isLoading) return <Spinner />
  if (!ratesQ.data) return null

  async function save(task) {
    const raw = drafts[task]
    const seconds = Number(raw)
    if (!Number.isInteger(seconds) || seconds < 5 || seconds > 3600) {
      toast.error('Enter a whole number of seconds between 5 and 3600.')
      return
    }
    setBusyTask(task)
    try {
      await kpiSettingsApi.set(task, seconds)
      toast.success(`${CHECK_META[task]?.label || task} now refreshes every ${seconds}s.`)
      setDrafts((d) => { const next = { ...d }; delete next[task]; return next })
      ratesQ.refetch()
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusyTask(null)
    }
  }

  async function reset(task) {
    setBusyTask(task)
    try {
      await kpiSettingsApi.reset(task)
      toast.success(`${CHECK_META[task]?.label || task} reset to the cluster default.`)
      setDrafts((d) => { const next = { ...d }; delete next[task]; return next })
      ratesQ.refetch()
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusyTask(null)
    }
  }

  return (
    <div className="space-y-2">
      {ratesQ.data.map((row) => {
        const meta = CHECK_META[row.task] || { label: row.task, icon: '📊' }
        const draft = drafts[row.task]
        const dirty = draft !== undefined && Number(draft) !== row.seconds
        const busy = busyTask === row.task
        return (
          <div key={row.task} className="flex items-center gap-3 rounded-xl border p-3" style={{ borderColor: 'var(--line)' }}>
            <span className="text-lg">{meta.icon}</span>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>{meta.label}</div>
              <div className="text-xs" style={{ color: 'var(--faint)' }}>
                {row.is_override ? 'Custom' : 'Cluster default'} · every {row.seconds}s
              </div>
            </div>
            <input
              type="number" min={5} max={3600} disabled={busy}
              value={draft ?? row.seconds}
              onChange={(e) => setDrafts((d) => ({ ...d, [row.task]: e.target.value }))}
              className="w-20 rounded-lg border px-2 py-1.5 text-sm text-right"
              style={{ background: 'var(--surface-2)', borderColor: 'var(--line)', color: 'var(--ink)' }}
            />
            <span className="text-xs" style={{ color: 'var(--faint)' }}>sec</span>
            <Button variant="subtle" onClick={() => save(row.task)} loading={busy} disabled={!dirty}>Save</Button>
            {row.is_override && <Button variant="ghost" onClick={() => reset(row.task)} disabled={busy}>Reset</Button>}
          </div>
        )
      })}
    </div>
  )
}
