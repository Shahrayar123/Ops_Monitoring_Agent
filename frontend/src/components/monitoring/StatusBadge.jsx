const MAP = {
  OK: { label: 'HEALTHY', cls: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-500/15 dark:text-emerald-300' },
  BREACH: { label: 'BREACH', cls: 'bg-red-100 text-red-700 dark:bg-red-500/15 dark:text-red-300' },
  NO_DATA: { label: 'NO DATA', cls: 'bg-slate-100 text-slate-500 dark:bg-slate-500/15 dark:text-slate-400' },
}

export function StatusBadge({ status }) {
  const s = MAP[status] || MAP.NO_DATA
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-[10px] font-extrabold tracking-wide ${s.cls}`}>
      {s.label}
    </span>
  )
}

// Left accent bar color per status.
export const statusAccent = (status) =>
  status === 'BREACH' ? '#ef4444' : status === 'NO_DATA' ? '#cbd5e1' : '#22c55e'
