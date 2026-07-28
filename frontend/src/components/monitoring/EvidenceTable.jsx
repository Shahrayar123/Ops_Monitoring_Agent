// The "what was checked, and where from" panel — scrollable, green (within
// limits) / red (breaching) per reading, with the source file / endpoint shown.
export function EvidenceTable({ evidence }) {
  if (!evidence || !evidence.rows?.length) {
    return <p className="text-xs" style={{ color: 'var(--faint)' }}>No per-reading data for this check.</p>
  }
  const over = evidence.rows.filter((r) => r.breached).length
  return (
    <div>
      <div className="mb-2 text-[11px] leading-relaxed" style={{ color: 'var(--muted)' }}>
        Keys: <code className="rounded bg-black/5 px-1.5 py-0.5 dark:bg-white/10">{evidence.keys_checked.join(', ')}</code>
        <br />
        Source: <code className="rounded bg-black/5 px-1.5 py-0.5 dark:bg-white/10 break-all">{evidence.source}</code>
      </div>
      <div className="max-h-64 overflow-auto rounded-lg border" style={{ borderColor: 'var(--line)' }}>
        <table className="w-full text-xs">
          <thead className="sticky top-0" style={{ background: 'var(--surface)' }}>
            <tr style={{ color: 'var(--faint)' }}>
              <th className="w-6 px-2 py-1.5"></th>
              <th className="px-2 py-1.5 text-left font-bold uppercase tracking-wide text-[9px]">Reading</th>
              <th className="px-2 py-1.5 text-left font-bold uppercase tracking-wide text-[9px]">Value</th>
            </tr>
          </thead>
          <tbody>
            {evidence.rows.map((row, i) => (
              <tr
                key={i}
                className="border-t"
                style={{
                  borderColor: 'var(--line)',
                  background: row.breached ? 'rgba(239,68,68,0.07)' : 'rgba(34,197,94,0.06)',
                }}
              >
                <td className="px-2 py-1.5 text-center">
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ background: row.breached ? '#ef4444' : '#22c55e' }}
                  />
                </td>
                <td className="break-words px-2 py-1.5" style={{ color: 'var(--ink)' }}>{row.entity}</td>
                <td className="break-words px-2 py-1.5 font-semibold" style={{ color: 'var(--ink)' }}>{row.value}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-1.5 text-[11px]" style={{ color: 'var(--faint)' }}>
        {evidence.rows.length} reading{evidence.rows.length !== 1 ? 's' : ''}
        {over > 0 && ` · ${over} over limit`}
      </div>
    </div>
  )
}
