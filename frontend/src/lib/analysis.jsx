import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { analysisApi } from './analysisApi'
import { normalizeError } from './api'
import { useAuth } from './auth'

/**
 * Shared, persisted AI-analysis state.
 *
 * One entry per (cluster, check, day). Polling runs HERE (at the app root), not
 * in the page or card — so a job keeps progressing while you navigate around,
 * the dashboard can show "Processing"/"Completed" per KPI, and re-opening the
 * analysis shows the finished result instead of re-running it.
 *
 * Persistence: entries are mirrored to localStorage (namespaced per user), so a
 * page refresh keeps completed results and resumes still-running jobs. A `storage`
 * listener keeps multiple tabs in sync. Nothing re-runs until the user hits reset.
 */

const AnalysisContext = createContext(null)

const POLL_MS = 3000
const MAX_AGE_MS = 24 * 60 * 60 * 1000 // drop entries older than a day on load

const lsKey = (uid) => `ops.analysis.${uid || 'anon'}`
export const entryKey = (slug, task, asOf) => `${slug}|${task || '__incident__'}|${asOf || 'latest'}`

function load(uid) {
  try {
    const raw = JSON.parse(localStorage.getItem(lsKey(uid)) || '{}')
    const now = Date.now()
    const kept = {}
    for (const [k, e] of Object.entries(raw)) {
      if (!e?.completedAt || now - e.completedAt < MAX_AGE_MS) kept[k] = e
    }
    return kept
  } catch {
    return {}
  }
}

function save(uid, entries) {
  try {
    localStorage.setItem(lsKey(uid), JSON.stringify(entries))
  } catch {
    /* quota / disabled storage — in-memory still works */
  }
}

export function AnalysisProvider({ children }) {
  const { user } = useAuth()
  const uid = user?.id
  const [entries, setEntries] = useState({})
  const entriesRef = useRef({})
  const timers = useRef({})

  const setEntry = useCallback((key, patch) => {
    setEntries((prev) => {
      const next = { ...prev, [key]: { ...prev[key], ...patch } }
      entriesRef.current = next
      save(uid, next)
      return next
    })
  }, [uid])

  const clearTimer = (key) => {
    if (timers.current[key]) {
      clearTimeout(timers.current[key])
      timers.current[key] = null
    }
  }

  const poll = useCallback(async (key) => {
    const e = entriesRef.current[key]
    if (!e || e.status !== 'running' || !e.jobId) {
      clearTimer(key)
      return
    }
    try {
      const job = await analysisApi.poll(e.jobId)
      if (job.status === 'running') {
        timers.current[key] = setTimeout(() => poll(key), POLL_MS)
        return
      }
      clearTimer(key)
      if (job.status === 'done') setEntry(key, { status: 'done', result: job.result, seconds: job.seconds, completedAt: Date.now() })
      else if (job.status === 'no_breach') setEntry(key, { status: 'no_breach', error: job.error, completedAt: Date.now() })
      else setEntry(key, { status: 'error', error: job.error || 'Analysis failed.', completedAt: Date.now() })
    } catch (err) {
      clearTimer(key)
      const n = normalizeError(err)
      const msg = n.status === 404 ? 'This analysis expired on the server — reset to run it again.' : n.message
      setEntry(key, { status: 'error', error: msg, completedAt: Date.now() })
    }
  }, [setEntry])

  // Ensure exactly one poll loop exists for a still-running entry.
  const ensurePoll = useCallback((key) => {
    if (!timers.current[key]) poll(key)
  }, [poll])

  const start = useCallback(async (kind, slug, task, asOf) => {
    const key = entryKey(slug, task, asOf)
    // Idempotent against localStorage (the source of truth), not just React
    // state — this guards the hydration race where a fresh page load auto-starts
    // before the saved entry has been loaded into state, which would otherwise
    // clobber an already-completed analysis.
    const existing = entriesRef.current[key] || load(uid)[key]
    if (existing && ['running', 'done', 'no_breach'].includes(existing.status)) {
      if (!entriesRef.current[key]) setEntry(key, existing)      // adopt persisted into state
      if (existing.status === 'running' && existing.jobId) ensurePoll(key)
      return
    }
    setEntry(key, { kind, slug, task: task || null, asOf: asOf || null, status: 'running', startedAt: Date.now(), jobId: null, result: null, error: null, seconds: 0 })
    try {
      const started = kind === 'incident' ? await analysisApi.startIncident(slug, asOf) : await analysisApi.startKpi(slug, task, asOf)
      setEntry(key, { jobId: started.job_id })
      poll(key)
    } catch (err) {
      setEntry(key, { status: 'error', error: normalizeError(err).message, completedAt: Date.now() })
    }
  }, [poll, setEntry, ensurePoll, uid])

  const reset = useCallback((slug, task, asOf) => {
    const key = entryKey(slug, task, asOf)
    clearTimer(key)
    setEntries((prev) => {
      const next = { ...prev }
      delete next[key]
      entriesRef.current = next
      save(uid, next)
      return next
    })
  }, [uid])

  // Hydrate on login / user change, resume running jobs, and sync across tabs.
  useEffect(() => {
    const hydrate = () => {
      const loaded = load(uid)
      entriesRef.current = loaded
      setEntries(loaded)
      for (const [key, e] of Object.entries(loaded)) {
        if (e.status === 'running' && e.jobId) ensurePoll(key)
        // Only a genuinely stale start (mid-POST across a reload) is "interrupted";
        // a just-started one whose POST is still in flight is left alone.
        else if (e.status === 'running' && !e.jobId && Date.now() - (e.startedAt || 0) > 10000)
          setEntry(key, { status: 'error', error: 'Analysis was interrupted — reset to run it again.', completedAt: Date.now() })
      }
    }
    hydrate()
    const onStorage = (ev) => { if (ev.key === lsKey(uid)) hydrate() }
    window.addEventListener('storage', onStorage)
    return () => {
      window.removeEventListener('storage', onStorage)
      Object.keys(timers.current).forEach(clearTimer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uid])

  return (
    <AnalysisContext.Provider value={{ entries, start, reset }}>
      {children}
    </AnalysisContext.Provider>
  )
}

// Aggregate AI status across the given checks (+ the incident report) for the
// dashboard's "AI status" strip.
export function useAnalysisCounts(slug, asOf, tasks = []) {
  const ctx = useContext(AnalysisContext)
  const counts = { processing: 0, ready: 0, failed: 0 }
  for (const t of [...tasks, null]) {
    const e = ctx.entries[entryKey(slug, t, asOf)]
    if (!e) continue
    if (e.status === 'running') counts.processing++
    else if (e.status === 'done') counts.ready++
    else if (e.status === 'error') counts.failed++
  }
  return counts
}

// Selector hook for one (cluster, check, day). task=null -> the incident report.
export function useAnalysis(slug, task, asOf) {
  const ctx = useContext(AnalysisContext)
  const key = entryKey(slug, task, asOf)
  const entry = ctx.entries[key] || null
  const kind = task ? 'kpi' : 'incident'
  return {
    status: entry?.status || 'idle',
    result: entry?.result || null,
    error: entry?.error || null,
    seconds: entry?.seconds || 0,
    startedAt: entry?.startedAt || null,
    start: () => ctx.start(kind, slug, task, asOf),
    reset: () => ctx.reset(slug, task, asOf),
  }
}
