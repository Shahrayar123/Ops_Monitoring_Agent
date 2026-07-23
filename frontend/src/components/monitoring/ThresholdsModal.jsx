import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Button, Input } from '../ui'
import { monitoringApi } from '../../lib/monitoringApi'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'

const NUM_FIELDS = [
  { key: 'cpu_pct', label: 'CPU limit (%)' },
  { key: 'ram_pct', label: 'Memory limit (%)' },
  { key: 'disk_pct', label: 'Disk limit (%)' },
  { key: 'heartbeat_window_sec', label: 'Heartbeat window (sec)' },
  { key: 'log_size_mb', label: 'Max log file size (MB)' },
  { key: 'hdfs_growth_pct_threshold', label: 'HDFS growth limit (%)' },
  { key: 'hdfs_growth_pct_window_hours', label: 'HDFS growth window (h)' },
  { key: 'network_error_rate_threshold', label: 'Network error rate limit' },
]

export function ThresholdsModal({ slug, onClose, onSaved }) {
  const toast = useToast()
  const [values, setValues] = useState(null)
  const [mounts, setMounts] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    monitoringApi.getThresholds(slug).then((t) => {
      setValues(t)
      setMounts((t.disk_mounts || []).join('\n'))
    })
  }, [slug])

  async function save() {
    setBusy(true)
    try {
      const payload = { ...values, disk_mounts: mounts.split('\n').map((m) => m.trim()).filter(Boolean) }
      await monitoringApi.updateThresholds(slug, payload)
      toast.success('Thresholds saved — re-running checks.')
      onSaved?.()
      onClose()
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" onClick={onClose}>
      <div
        className="card max-h-[88vh] w-full max-w-2xl overflow-auto p-6 animate-fade-in"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-bold" style={{ color: 'var(--ink)' }}>
            Edit thresholds
          </h3>
          <button onClick={onClose} className="text-xl" style={{ color: 'var(--faint)' }}>×</button>
        </div>

        {!values ? (
          <div className="skeleton h-64 rounded-xl" />
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              {NUM_FIELDS.map((f) => (
                <Input
                  key={f.key}
                  label={f.label}
                  type="number"
                  step="any"
                  value={values[f.key] ?? ''}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value === '' ? '' : Number(e.target.value) }))}
                />
              ))}
            </div>
            <label className="mt-4 block">
              <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>
                Disk mounts to watch (one per line)
              </span>
              <textarea
                rows={6}
                value={mounts}
                onChange={(e) => setMounts(e.target.value)}
                className="w-full rounded-xl border px-3.5 py-2.5 text-sm font-mono outline-none focus:ring-2 focus:ring-brand-400/50"
                style={{ background: 'var(--surface-2)', borderColor: 'var(--line)', color: 'var(--ink)' }}
              />
            </label>
            <div className="mt-5 flex justify-end gap-3">
              <Button variant="subtle" onClick={onClose}>Cancel</Button>
              <Button onClick={save} loading={busy}>Save thresholds</Button>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body
  )
}
