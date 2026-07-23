import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { Button, Card, Spinner } from '../components/ui'
import { CHECK_META } from '../lib/monitoringApi'
import { useAnalysis } from '../lib/analysis'
import { useToast } from '../lib/toast'
import { SeverityBadge } from '../components/analysis/SeverityBadge'

// A dedicated page for one breaching KPI's AI analysis. Opened from the card's
// "AI Analyzer" button; it has its own URL so it can be opened in a new tab.
// State comes from the shared store — so it never re-runs an analysis that's
// already done, and a still-running job keeps progressing if you navigate away.
export default function KpiAnalysis() {
  const { slug, task } = useParams()
  const [params] = useSearchParams()
  const asOf = params.get('as_of') || null
  const meta = CHECK_META[task] || { label: task, icon: '•' }
  const job = useAnalysis(slug, task, asOf)
  const toast = useToast()

  // Kick off once if nothing exists yet; idempotent for done/running entries.
  useEffect(() => {
    if (job.status === 'idle') job.start()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slug, task, asOf, job.status])

  const elapsed = useElapsed(job.startedAt, job.status === 'running')
  const a = job.result

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-5 flex items-center justify-between">
        <Link to="/dashboard" className="text-sm font-semibold text-brand-600">← Back to dashboard</Link>
        {asOf && <span className="text-xs" style={{ color: 'var(--faint)' }}>as of {asOf}</span>}
      </div>

      <div className="mb-6 flex items-center gap-3">
        <span className="text-3xl">{meta.icon}</span>
        <div>
          <h1 className="text-xl font-bold tracking-tight" style={{ color: 'var(--ink)' }}>{meta.label}</h1>
          <p className="text-sm" style={{ color: 'var(--muted)' }}>AI incident analysis · {slug}</p>
        </div>
        {a && <div className="ml-auto flex items-center gap-2">
          <SeverityBadge severity={a.severity} />
          <button onClick={() => { job.reset(); job.start() }} title="Reset & re-analyze"
            className="grid h-8 w-8 place-items-center rounded-lg border text-sm transition hover:bg-black/5 dark:hover:bg-white/5"
            style={{ borderColor: 'var(--line)', color: 'var(--muted)' }}>↺</button>
        </div>}
      </div>

      {job.status === 'running' && (
        <Card className="grid place-items-center py-16 text-center">
          <Spinner className="h-8 w-8 text-brand-600" />
          <p className="mt-4 text-sm font-semibold" style={{ color: 'var(--ink)' }}>Analyzing…</p>
          <p className="mt-1 text-xs" style={{ color: 'var(--muted)' }}>
            Running on your selected model. Local models can take a few minutes — {elapsed}s elapsed.
          </p>
          <p className="mt-3 text-xs" style={{ color: 'var(--faint)' }}>You can leave this page — it keeps running.</p>
        </Card>
      )}

      {job.status === 'no_breach' && (
        <Card className="text-center py-12">
          <div className="text-4xl">✅</div>
          <p className="mt-2 text-sm" style={{ color: 'var(--muted)' }}>{job.error}</p>
        </Card>
      )}

      {job.status === 'error' && (
        <Card className="border-l-4 border-l-red-500">
          <h3 className="text-base font-bold" style={{ color: 'var(--ink)' }}>Analysis couldn't run</h3>
          <p className="mt-2 text-sm" style={{ color: 'var(--muted)' }}>{job.error}</p>
          <Button className="mt-4" onClick={() => { job.reset(); job.start() }}>Try again</Button>
        </Card>
      )}

      {job.status === 'done' && a && (
        <div className="space-y-5">
          <Section title="Summary">
            <p className="text-sm leading-relaxed" style={{ color: 'var(--ink)' }}>{a.summary}</p>
          </Section>

          {a.remediation?.length > 0 && (
            <Section title="Recommended remediation">
              <ol className="space-y-2">
                {a.remediation.map((step, i) => (
                  <li key={i} className="flex gap-3 text-sm" style={{ color: 'var(--ink)' }}>
                    <span className="grid h-6 w-6 flex-none place-items-center rounded-full bg-brand-600 text-xs font-bold text-white">{i + 1}</span>
                    <span className="leading-relaxed">{step}</span>
                  </li>
                ))}
              </ol>
            </Section>
          )}

          {a.impact && (
            <Section title="Impact on other metrics">
              <p className="text-sm leading-relaxed" style={{ color: 'var(--ink)' }}>{a.impact}</p>
              {a.related_tasks?.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {a.related_tasks.map((t) => (
                    <Link key={t} to={`/dashboard/${slug}/${t}/analysis${asOf ? `?as_of=${asOf}` : ''}`}
                      className="rounded-lg bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-700 hover:bg-amber-200 dark:bg-amber-500/15 dark:text-amber-300">
                      {(CHECK_META[t]?.label) || t} →
                    </Link>
                  ))}
                </div>
              )}
            </Section>
          )}

          {a.trend_note && (
            <Section title="Projected trend">
              <pre className="whitespace-pre-wrap text-xs leading-relaxed" style={{ color: 'var(--muted)' }}>{a.trend_note}</pre>
            </Section>
          )}

          {/* Agentic remediation — placeholder for now */}
          <Card className="flex flex-wrap items-center justify-between gap-3 border-dashed">
            <div>
              <div className="text-sm font-bold" style={{ color: 'var(--ink)' }}>⚡ Run Agent</div>
              <div className="text-xs" style={{ color: 'var(--muted)' }}>Let AI agents apply the remediation automatically (coming soon).</div>
            </div>
            <Button onClick={() => toast.info('Agentic remediation is coming in a later release.')}>Run Agent</Button>
          </Card>

          <GovernanceFooter analysis={a} seconds={job.seconds} />
        </div>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <Card>
      <h3 className="mb-3 text-sm font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>{title}</h3>
      {children}
    </Card>
  )
}

// Live-ticking elapsed seconds since `startedAt` while `active`.
function useElapsed(startedAt, active) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [active])
  return startedAt ? Math.max(0, Math.round((now - startedAt) / 1000)) : 0
}

function GovernanceFooter({ analysis, seconds }) {
  return (
    <div className="rounded-xl border p-4 text-xs" style={{ borderColor: 'var(--line)', color: 'var(--muted)' }}>
      <div className="flex flex-wrap gap-x-6 gap-y-1">
        <span>🤖 Model: <b style={{ color: 'var(--ink)' }}>{analysis.model_used}</b></span>
        {analysis.sources?.length > 0 && <span>📚 Sources: {[...new Set(analysis.sources)].join(', ')}</span>}
        <span>⏱ {seconds}s</span>
      </div>
      <p className="mt-2">
        🛡️ Governed: detection is deterministic (the AI never decides what's wrong); severity is floored by the check data so it can't be under-rated.
        {analysis.attempts?.length > 1 && ' Model fallback was used.'}
      </p>
    </div>
  )
}
