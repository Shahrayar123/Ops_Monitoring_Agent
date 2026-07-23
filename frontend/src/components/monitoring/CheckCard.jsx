import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { CHECK_META, monitoringApi } from '../../lib/monitoringApi'
import { useAnalysis } from '../../lib/analysis'
import { StatusBadge, statusAccent } from './StatusBadge'
import { EvidenceTable } from './EvidenceTable'

function formatRate(sec) {
  if (sec % 3600 === 0) return `${sec / 3600}h`
  if (sec % 60 === 0) return `${sec / 60}m`
  return `${sec}s`
}

// One check card. It owns its OWN polling query on its OWN interval, so a 15s
// alerts card and a 10-minute HDFS card refresh independently — the per-metric
// refresh management asked for. Fresh results are lifted to the parent via
// onResult so the health ring stays current.
export function CheckCard({ slug, task, asOf, rate, seed, onResult, affectedBy = [] }) {
  const meta = CHECK_META[task] || { label: task, icon: '•' }
  const [open, setOpen] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(() => Date.now())

  const q = useQuery({
    queryKey: ['check', slug, task, asOf],
    queryFn: () => monitoringApi.check(slug, task, asOf),
    initialData: seed,
    refetchInterval: rate * 1000,
    refetchOnWindowFocus: false,
  })

  const result = q.data
  useEffect(() => {
    if (q.dataUpdatedAt) setUpdatedAt(q.dataUpdatedAt)
  }, [q.dataUpdatedAt])
  useEffect(() => {
    if (result) onResult?.(task, result)
  }, [result, task, onResult])

  if (!result) return <div className="skeleton h-40 rounded-2xl" />

  const evidence = result.evidence
  const over = evidence?.rows?.filter((r) => r.breached).length || 0
  const isBreach = result.status === 'BREACH'
  // Show a "may be affected" hint only when a parent check is itself breaching.
  const affectingNow = affectedBy.filter((p) => p.breaching).map((p) => p.task)
  const analysisHref = `/dashboard/${slug}/${task}/analysis${asOf ? `?as_of=${asOf}` : ''}`

  return (
    <div
      className="card min-w-0 overflow-hidden transition hover:-translate-y-0.5 hover:shadow-lg"
      style={{ borderLeft: `4px solid ${statusAccent(result.status)}` }}
    >
      <div className="p-4">
        <div className="flex items-center gap-2.5">
          <span className="text-lg">{meta.icon}</span>
          <span className="flex-1 text-sm font-bold" style={{ color: 'var(--ink)' }}>
            {meta.label}
          </span>
          <StatusBadge status={result.status} />
        </div>

        <p className="mt-2.5 break-words text-[12.5px] leading-relaxed" style={{ color: 'var(--muted)' }}>
          {result.detail}
        </p>

        {affectingNow.length > 0 && !isBreach && (
          <div className="mt-2 break-words rounded-lg bg-amber-50 px-2.5 py-1.5 text-[11px] font-medium text-amber-700 dark:bg-amber-500/10 dark:text-amber-300">
            ⚠ may be affected by {affectingNow.map((t) => CHECK_META[t]?.label || t).join(', ')}
          </div>
        )}

        <div className="mt-3 flex items-center justify-between text-[11px]" style={{ color: 'var(--faint)' }}>
          <span title="This card's own refresh interval" className="flex items-center gap-1">
            <span className={`inline-block h-1.5 w-1.5 rounded-full ${q.isFetching ? 'bg-brand-500 animate-pulse' : 'bg-emerald-500'}`} />
            every {formatRate(rate)}
          </span>
          <LastUpdated ts={updatedAt} />
        </div>

        {isBreach && <AiSection slug={slug} task={task} asOf={asOf} href={analysisHref} />}
      </div>

      {evidence?.rows?.length > 0 && (
        <>
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex w-full items-center justify-between border-t px-4 py-2.5 text-xs font-semibold text-brand-600 transition hover:bg-brand-50/60 dark:hover:bg-brand-500/10"
            style={{ borderColor: 'var(--line)' }}
          >
            <span>🔍 Data checked — {evidence.rows.length} reading{evidence.rows.length !== 1 ? 's' : ''}{over > 0 ? ` · ${over} over limit` : ''}</span>
            <span className={`transition ${open ? 'rotate-180' : ''}`}>▾</span>
          </button>
          {open && (
            <div className="border-t p-4" style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}>
              <EvidenceTable evidence={evidence} />
            </div>
          )}
        </>
      )}
    </div>
  )
}

function LastUpdated({ ts }) {
  const [, tick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [])
  const secs = Math.max(0, Math.round((Date.now() - ts) / 1000))
  const label = secs < 2 ? 'just now' : secs < 60 ? `${secs}s ago` : `${Math.floor(secs / 60)}m ago`
  return <span>updated {label}</span>
}

// The per-card AI status + actions, driven by the shared analysis store so it
// reflects Processing/Completed even after you navigate away and come back, and
// never re-runs a finished analysis (reset first).
function AiSection({ slug, task, asOf, href }) {
  const job = useAnalysis(slug, task, asOf)
  const [, tick] = useState(0)
  useEffect(() => {
    if (job.status !== 'running') return
    const id = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [job.status])
  const elapsed = job.startedAt ? Math.max(0, Math.round((Date.now() - job.startedAt) / 1000)) : 0

  if (job.status === 'running') {
    return (
      <Link to={href} className="mt-3 flex items-center justify-center gap-2 rounded-xl border border-brand-400/50 bg-brand-50 py-2 text-xs font-bold text-brand-700 transition hover:bg-brand-100 dark:bg-brand-500/10 dark:text-brand-300">
        <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-brand-500" />
        AI processing… {elapsed}s · view
      </Link>
    )
  }

  if (job.status === 'done') {
    const sev = job.result?.severity
    return (
      <div className="mt-3 flex items-center gap-2">
        <Link to={href} className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-emerald-600 py-2 text-xs font-bold text-white transition hover:bg-emerald-700">
          ✅ Analysis ready{sev ? ` · ${sev}` : ''} · view
        </Link>
        <button onClick={job.reset} title="Reset AI analysis"
          className="grid h-8 w-8 flex-none place-items-center rounded-xl border text-sm transition hover:bg-black/5 dark:hover:bg-white/5"
          style={{ borderColor: 'var(--line)', color: 'var(--muted)' }}>↺</button>
      </div>
    )
  }

  if (job.status === 'error') {
    return (
      <div className="mt-3 flex items-center gap-2">
        <Link to={href} className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-red-600 py-2 text-xs font-bold text-white transition hover:bg-red-700">
          ⚠ Analysis failed · view
        </Link>
        <button onClick={job.reset} title="Reset"
          className="grid h-8 w-8 flex-none place-items-center rounded-xl border text-sm transition hover:bg-black/5 dark:hover:bg-white/5"
          style={{ borderColor: 'var(--line)', color: 'var(--muted)' }}>↺</button>
      </div>
    )
  }

  // idle
  return (
    <Link to={href} onClick={job.start}
      className="mt-3 flex items-center justify-center gap-2 rounded-xl bg-brand-600 py-2 text-xs font-bold text-white transition hover:bg-brand-700">
      🧠 AI Analyzer
    </Link>
  )
}
