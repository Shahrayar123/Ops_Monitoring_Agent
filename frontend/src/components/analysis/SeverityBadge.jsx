const STYLES = {
  CRITICAL: 'bg-red-900 text-white',
  HIGH: 'bg-red-600 text-white',
  MEDIUM: 'bg-amber-500 text-white',
  LOW: 'bg-brand-600 text-white',
}

export function SeverityBadge({ severity }) {
  const cls = STYLES[severity] || STYLES.MEDIUM
  return (
    <span className={`rounded-lg px-3 py-1 text-xs font-extrabold tracking-wide ${cls}`}>
      {severity}
    </span>
  )
}
