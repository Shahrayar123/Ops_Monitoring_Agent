// Daily/monthly AI-call and token meters. A limit of 0 means unlimited.
// Limits are admin-set (shown read-only here).
export function UsageMeter({ usage }) {
  return (
    <>
      <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Calls</div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Bar label="Today" used={usage.used_today} limit={usage.daily_limit} />
        <Bar label="This month" used={usage.used_month} limit={usage.monthly_limit} />
      </div>
      <div className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Tokens</div>
      <div className="grid gap-4 sm:grid-cols-2">
        <Bar label="Today" used={usage.tokens_today} limit={usage.daily_token_limit} fmt />
        <Bar label="This month" used={usage.tokens_month} limit={usage.monthly_token_limit} fmt />
      </div>
      <p className="mt-4 text-xs" style={{ color: 'var(--faint)' }}>Limits are set by your administrator.</p>
    </>
  )
}

function Bar({ label, used, limit, fmt }) {
  const unlimited = !limit
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100))
  const color = pct >= 100 ? '#dc2626' : pct >= 80 ? '#d97706' : '#4f46e5'
  const show = (n) => (fmt ? n.toLocaleString() : n)
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-sm">
        <span style={{ color: 'var(--muted)' }}>{label}</span>
        <span className="font-semibold" style={{ color: 'var(--ink)' }}>
          {show(used)}{unlimited ? '' : ` / ${show(limit)}`}
          {unlimited && <span className="ml-1 text-xs font-normal" style={{ color: 'var(--faint)' }}>(unlimited)</span>}
        </span>
      </div>
      <div className="h-2 overflow-hidden rounded-full" style={{ background: 'var(--surface-2)' }}>
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: unlimited ? '8%' : `${pct}%`, background: unlimited ? 'var(--line)' : color }}
        />
      </div>
    </div>
  )
}
