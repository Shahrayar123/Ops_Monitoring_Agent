import { useCallback, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Spinner } from '../components/ui'
import { monitoringApi } from '../lib/monitoringApi'
import { analysisApi } from '../lib/analysisApi'
import { useAnalysisCounts } from '../lib/analysis'
import { HealthRing } from '../components/monitoring/HealthRing'
import { CheckCard } from '../components/monitoring/CheckCard'
import { ThresholdsModal } from '../components/monitoring/ThresholdsModal'
import { IncidentAnalysis } from '../components/analysis/IncidentAnalysis'
import { useAuth } from '../lib/auth'

const CHECK_ORDER = [
  'host_health', 'heartbeat', 'cpu_percent', 'ram_percent', 'disk_percent',
  'hdfs_health', 'service_status', 'alerts', 'network',
]

const SOURCE_BADGE = {
  json: { label: '📄 Export files', cls: 'bg-slate-100 text-slate-600 dark:bg-slate-500/15 dark:text-slate-300' },
  api: { label: '🌐 Live API', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' },
}

export default function Dashboard() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [slug, setSlug] = useState(null)
  const [asOf, setAsOf] = useState(null)
  const [liveResults, setLiveResults] = useState({})
  const [editing, setEditing] = useState(false)

  const tenantsQ = useQuery({ queryKey: ['tenants'], queryFn: monitoringApi.listTenants })

  // Default to the first tenant once loaded.
  const activeSlug = slug || tenantsQ.data?.[0]?.slug || null

  const datesQ = useQuery({
    queryKey: ['dates', activeSlug],
    queryFn: () => monitoringApi.dates(activeSlug),
    enabled: !!activeSlug,
  })
  const dates = datesQ.data || []
  const activeDate = asOf ?? (dates.length ? dates[dates.length - 1] : null)

  const reportQ = useQuery({
    queryKey: ['report', activeSlug, activeDate],
    queryFn: () => monitoringApi.report(activeSlug, activeDate),
    enabled: !!activeSlug,
  })

  // The dependency map (static per cluster) drives the "may be affected by X" chips.
  const depsQ = useQuery({
    queryKey: ['dependencies', activeSlug],
    queryFn: () => analysisApi.dependencies(activeSlug),
    enabled: !!activeSlug,
    staleTime: Infinity,
  })

  const onResult = useCallback((task, result) => {
    setLiveResults((prev) => (prev[task] === result ? prev : { ...prev, [task]: result }))
  }, [])

  // Health summary is derived from the live per-card results (falling back to
  // the initial bundle), so the ring reflects the freshest state each card has.
  const summary = useMemo(() => {
    const results = reportQ.data?.results || []
    const merged = results.map((r) => liveResults[r.task] || r)
    const evaluated = merged.filter((r) => r.status !== 'NO_DATA').length
    const passing = merged.filter((r) => r.status === 'OK').length
    const breaches = merged.filter((r) => r.status === 'BREACH').length
    const noData = merged.filter((r) => r.status === 'NO_DATA').length
    return { evaluated, passing, breaches, noData }
  }, [reportQ.data, liveResults])

  const seedByTask = useMemo(() => {
    const m = {}
    for (const r of reportQ.data?.results || []) m[r.task] = r
    return m
  }, [reportQ.data])

  const rates = reportQ.data?.refresh_rates || {}
  const mode = reportQ.data?.data_source_mode
  const tenant = tenantsQ.data?.find((t) => t.slug === activeSlug)

  // Which tasks are currently breaching (from the freshest per-card results).
  const breachingSet = useMemo(() => {
    const merged = (reportQ.data?.results || []).map((r) => liveResults[r.task] || r)
    return new Set(merged.filter((r) => r.status === 'BREACH').map((r) => r.task))
  }, [reportQ.data, liveResults])

  // For each task, the parent checks that list it as affected, with live breach state.
  const affectedByMap = depsQ.data?.affected_by || {}
  const affectedFor = useCallback(
    (task) => (affectedByMap[task] || []).map((p) => ({ task: p, breaching: breachingSet.has(p) })),
    [affectedByMap, breachingSet]
  )

  const aiCounts = useAnalysisCounts(activeSlug, activeDate, CHECK_ORDER)

  function switchTenant(s) {
    setSlug(s)
    setAsOf(null)
    setLiveResults({})
  }
  function refreshAll() {
    setLiveResults({})
    queryClient.invalidateQueries({ queryKey: ['report', activeSlug] })
    queryClient.invalidateQueries({ queryKey: ['check', activeSlug] })
  }

  if (tenantsQ.isLoading) return <CenterSpinner />
  if (!activeSlug)
    return (
      <Card className="grid place-items-center py-16 text-center">
        <div className="text-5xl">🗂️</div>
        <h3 className="mt-3 text-lg font-bold" style={{ color: 'var(--ink)' }}>No clusters yet</h3>
        <p className="mt-1 text-sm" style={{ color: 'var(--muted)' }}>
          {user?.role === 'admin' ? 'Add a cluster from the Admin panel to start monitoring.' : 'Ask an admin to give you access to a cluster.'}
        </p>
      </Card>
    )

  return (
    <>
      {/* Controls */}
      <div className="mb-6 flex flex-wrap items-center gap-3">
        <select
          value={activeSlug}
          onChange={(e) => switchTenant(e.target.value)}
          className="rounded-xl border px-3.5 py-2.5 text-sm font-semibold outline-none"
          style={{ background: 'var(--surface)', borderColor: 'var(--line)', color: 'var(--ink)' }}
        >
          {tenantsQ.data.map((t) => (
            <option key={t.slug} value={t.slug}>{t.display_name}</option>
          ))}
        </select>

        {dates.length > 0 && (
          <select
            value={activeDate || ''}
            onChange={(e) => { setAsOf(e.target.value); setLiveResults({}) }}
            className="rounded-xl border px-3.5 py-2.5 text-sm outline-none"
            style={{ background: 'var(--surface)', borderColor: 'var(--line)', color: 'var(--ink)' }}
            title="View the cluster's state as of this day"
          >
            {dates.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        )}

        {mode && (
          <span className={`rounded-full px-3 py-1.5 text-xs font-semibold ${SOURCE_BADGE[mode]?.cls}`}>
            {SOURCE_BADGE[mode]?.label}
          </span>
        )}
        {reportQ.data?.cloudera_version && (
          <span className="rounded-full bg-brand-50 px-3 py-1.5 text-xs font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">
            CDP {reportQ.data.cloudera_version}
          </span>
        )}

        <div className="ml-auto flex gap-2">
          <Button variant="subtle" onClick={() => setEditing(true)}>⚙️ Thresholds</Button>
          <Button variant="subtle" onClick={refreshAll}>🔄 Refresh</Button>
        </div>
      </div>

      {reportQ.isError ? (
        <SourceError error={reportQ.error} isAdmin={user?.role === 'admin'} />
      ) : reportQ.isLoading ? (
        <CenterSpinner />
      ) : (
        <>
          {/* Overview */}
          <Card className="mb-6 flex flex-wrap items-center gap-6">
            <HealthRing passing={summary.passing} evaluated={summary.evaluated} />
            <div className="flex flex-1 flex-wrap gap-6">
              <Stat label="Cluster" value={tenant?.cluster_name} wide />
              <Stat label="Checks run" value={summary.evaluated} />
              <Stat label="Passing" value={summary.passing} tone="green" />
              <Stat label="Issues" value={summary.breaches} tone={summary.breaches ? 'red' : 'green'} />
              {summary.noData > 0 && <Stat label="No data" value={summary.noData} />}
            </div>
            <div className="w-full space-y-2">
              <div
                className="rounded-xl px-4 py-3 text-sm font-semibold"
                style={{
                  background: summary.breaches ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)',
                  color: summary.breaches ? '#b91c1c' : '#15803d',
                }}
              >
                {summary.breaches
                  ? `⚠️ ${summary.breaches} issue${summary.breaches !== 1 ? 's' : ''} need attention across ${summary.evaluated} evaluated checks.`
                  : `✅ All ${summary.evaluated} evaluated checks are within thresholds.`}
              </div>
              {(aiCounts.processing + aiCounts.ready + aiCounts.failed) > 0 && (
                <div className="flex flex-wrap items-center gap-3 rounded-xl px-4 py-2 text-xs font-semibold"
                  style={{ background: 'var(--surface-2)', color: 'var(--muted)' }}>
                  <span>🧠 AI status:</span>
                  {aiCounts.processing > 0 && <span className="flex items-center gap-1.5 text-brand-600"><span className="inline-block h-2 w-2 animate-pulse rounded-full bg-brand-500" />{aiCounts.processing} processing</span>}
                  {aiCounts.ready > 0 && <span className="text-emerald-600">✅ {aiCounts.ready} completed</span>}
                  {aiCounts.failed > 0 && <span className="text-red-500">⚠ {aiCounts.failed} failed</span>}
                </div>
              )}
            </div>
          </Card>

          {/* The nine checks */}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {CHECK_ORDER.map((task) => (
              <CheckCard
                key={`${activeSlug}:${task}:${activeDate}`}
                slug={activeSlug}
                task={task}
                asOf={activeDate}
                rate={rates[task] || 30}
                seed={seedByTask[task]}
                onResult={onResult}
                affectedBy={affectedFor(task)}
              />
            ))}
          </div>

          {/* All-breaches AI incident analysis */}
          <IncidentAnalysis slug={activeSlug} asOf={activeDate} hasBreaches={summary.breaches > 0} />
        </>
      )}

      {editing && (
        <ThresholdsModal slug={activeSlug} onClose={() => setEditing(false)} onSaved={refreshAll} />
      )}
    </>
  )
}

function Stat({ label, value, tone, wide }) {
  const color = tone === 'green' ? '#16a34a' : tone === 'red' ? '#dc2626' : 'var(--ink)'
  return (
    <div className={wide ? 'min-w-[160px]' : ''}>
      <div className="text-[11px] font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>{label}</div>
      <div className="mt-1 text-2xl font-extrabold tracking-tight" style={{ color }}>{value ?? '—'}</div>
    </div>
  )
}

function CenterSpinner() {
  return <div className="grid place-items-center py-24"><Spinner className="h-8 w-8 text-brand-600" /></div>
}

function SourceError({ error, isAdmin }) {
  const is409 = error?.status === 409 || error?.code === 'conflict'
  return (
    <Card className="border-l-4 border-l-amber-500">
      <h3 className="text-base font-bold" style={{ color: 'var(--ink)' }}>
        {is409 ? "This cluster's data source isn't ready yet" : 'Could not load monitoring data'}
      </h3>
      <p className="mt-2 text-sm" style={{ color: 'var(--muted)' }}>{error?.message}</p>
      {is409 && isAdmin && (
        <p className="mt-2 text-sm" style={{ color: 'var(--muted)' }}>
          Upload this cluster's export files (or set up its live API connection) in the Admin panel.
        </p>
      )}
    </Card>
  )
}
