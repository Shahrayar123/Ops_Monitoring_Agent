import { useEffect, useState } from 'react'
import { Button, Card, Spinner } from '../ui'
import { CHECK_META } from '../../lib/monitoringApi'
import { useAnalysis } from '../../lib/analysis'
import { SeverityBadge } from './SeverityBadge'

// The dashboard-bottom "AI Incident Analysis" — one run across ALL breaches.
// Backed by the shared store (keyed as the incident report for this cluster/day),
// so it persists across navigation + refresh and never silently re-runs.
export function IncidentAnalysis({ slug, asOf, hasBreaches }) {
  const job = useAnalysis(slug, null, asOf)
  const report = job.result
  const elapsed = useTick(job.startedAt, job.status === 'running')

  return (
    <Card className="mt-8">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-base font-bold" style={{ color: 'var(--ink)' }}>🧠 AI Incident Analysis</h3>
          <p className="text-xs" style={{ color: 'var(--muted)' }}>All current breaches, connected and prioritised.</p>
        </div>
        {!hasBreaches ? (
          <span className="rounded-lg bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300">
            ✅ No breaches to analyze
          </span>
        ) : job.status === 'running' ? (
          <span className="flex items-center gap-2 rounded-lg bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 dark:bg-brand-500/10 dark:text-brand-300">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-brand-500" /> Processing… {elapsed}s
          </span>
        ) : report ? (
          <div className="flex items-center gap-2">
            <Button variant="subtle" onClick={() => { job.reset(); job.start() }}>🔄 Re-run</Button>
            <button onClick={job.reset} title="Reset analysis"
              className="grid h-9 w-9 place-items-center rounded-xl border text-sm transition hover:bg-black/5 dark:hover:bg-white/5"
              style={{ borderColor: 'var(--line)', color: 'var(--muted)' }}>↺</button>
          </div>
        ) : (
          <Button onClick={job.start}>🧠 Analyze all breaches</Button>
        )}
      </div>

      {job.status === 'running' && (
        <div className="grid place-items-center py-10 text-center">
          <Spinner className="h-7 w-7 text-brand-600" />
          <p className="mt-3 text-sm" style={{ color: 'var(--muted)' }}>
            Analyzing all breaches on your selected model — {elapsed}s elapsed. You can leave this page; it keeps running.
          </p>
        </div>
      )}

      {job.status === 'error' && <p className="text-sm text-red-500">{job.error}</p>}
      {job.status === 'no_breach' && <p className="text-sm" style={{ color: 'var(--muted)' }}>{job.error}</p>}

      {job.status === 'done' && report && (
        <div className="space-y-4">
          <div className="rounded-xl border p-4" style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}>
            <p className="text-sm leading-relaxed" style={{ color: 'var(--ink)' }}>{report.overall_summary}</p>
            {report.priority_order?.length > 0 && (
              <p className="mt-3 text-xs" style={{ color: 'var(--muted)' }}>
                Priority: {report.priority_order.map((t) => CHECK_META[t]?.label || t).join(' → ')}
              </p>
            )}
          </div>

          {report.findings?.map((f, i) => (
            <div key={i} className="rounded-xl border p-4" style={{ borderColor: 'var(--line)' }}>
              <div className="mb-2 flex items-center gap-2">
                <span className="text-base">{CHECK_META[f.primary_task]?.icon || '•'}</span>
                <span className="flex-1 text-sm font-bold" style={{ color: 'var(--ink)' }}>
                  {CHECK_META[f.primary_task]?.label || f.primary_task}
                </span>
                <SeverityBadge severity={f.severity} />
              </div>
              <p className="text-sm leading-relaxed" style={{ color: 'var(--ink)' }}>{f.summary}</p>
              {f.remediation?.length > 0 && (
                <ul className="mt-2 list-disc space-y-1 pl-5 text-[13px]" style={{ color: 'var(--muted)' }}>
                  {f.remediation.map((s, j) => <li key={j}>{s}</li>)}
                </ul>
              )}
              {f.related_tasks?.length > 0 && (
                <p className="mt-2 text-xs" style={{ color: 'var(--faint)' }}>
                  Affects: {f.related_tasks.map((t) => CHECK_META[t]?.label || t).join(', ')}
                </p>
              )}
            </div>
          ))}

          <p className="text-xs" style={{ color: 'var(--faint)' }}>
            🤖 {report.model_used} · 🛡️ severity floored by check data
          </p>
        </div>
      )}
    </Card>
  )
}

function useTick(startedAt, active) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])
  return startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0
}
