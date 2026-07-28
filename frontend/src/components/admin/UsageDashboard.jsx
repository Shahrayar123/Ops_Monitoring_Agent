import { useQuery } from '@tanstack/react-query'
import { Card, Spinner } from '../ui'
import { plansApi } from '../../lib/llmApi'

// Per-user AI usage across the fleet — today, this month, tokens, vs plan limits.
export function UsageDashboard() {
  const q = useQuery({ queryKey: ['admin-usage'], queryFn: plansApi.usage, refetchInterval: 10000 })
  if (q.isLoading) return <Spinner />

  const totalToday = q.data.users.reduce((s, u) => s + u.used_today, 0)
  const totalMonth = q.data.users.reduce((s, u) => s + u.used_month, 0)
  const totalTokens = q.data.users.reduce((s, u) => s + u.tokens_month, 0)

  return (
    <>
      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <Stat label="Calls today" value={totalToday} />
        <Stat label="Calls this month" value={totalMonth} />
        <Stat label="Tokens this month" value={totalTokens.toLocaleString()} />
      </div>
      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide" style={{ color: 'var(--faint)' }}>
                <th className="pb-2">User</th><th className="pb-2">Models (in use)</th><th className="pb-2">Calls today</th><th className="pb-2">Calls month</th><th className="pb-2">Tokens (mo)</th>
              </tr>
            </thead>
            <tbody>
              {q.data.users.map((u) => (
                <tr key={u.user_id} className="border-t" style={{ borderColor: 'var(--line)' }}>
                  <td className="py-2.5" style={{ color: 'var(--ink)' }}>{u.email}</td>
                  <td className="py-2.5">
                    {u.models?.length ? (
                      <span className="flex flex-wrap gap-1">
                        {u.models.map((m, i) => (
                          <span key={m} className="rounded bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">{i === 0 ? '★ ' : ''}{m}</span>
                        ))}
                      </span>
                    ) : <span style={{ color: 'var(--faint)' }}>—</span>}
                  </td>
                  <td className="py-2.5"><Limit used={u.used_today} limit={u.daily_limit} /></td>
                  <td className="py-2.5"><Limit used={u.used_month} limit={u.monthly_limit} /></td>
                  <td className="py-2.5">
                    <Limit used={u.tokens_month} limit={u.monthly_token_limit} fmt />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  )
}

function Limit({ used, limit, fmt }) {
  const over = limit && used >= limit
  const show = (n) => (fmt ? n.toLocaleString() : n)
  return (
    <span style={{ color: over ? '#dc2626' : 'var(--ink)' }} className={over ? 'font-bold' : ''}>
      {show(used)}{limit ? ` / ${show(limit)}` : ''}
    </span>
  )
}

function Stat({ label, value }) {
  return (
    <Card>
      <div className="text-[11px] font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>{label}</div>
      <div className="mt-1 text-2xl font-extrabold" style={{ color: 'var(--ink)' }}>{value}</div>
    </Card>
  )
}
