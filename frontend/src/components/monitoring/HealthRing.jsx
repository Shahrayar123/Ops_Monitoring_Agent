// Animated SVG donut showing cluster health % (passing / evaluated checks).
export function HealthRing({ passing, evaluated, size = 132 }) {
  const pct = evaluated ? Math.round((passing / evaluated) * 100) : 0
  const stroke = 12
  const r = (size - stroke) / 2
  const circ = 2 * Math.PI * r
  const offset = circ - (pct / 100) * circ
  const color = pct === 100 ? '#16a34a' : pct < 60 ? '#dc2626' : '#4f46e5'

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth={stroke} />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={color}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circ}
          strokeDashoffset={offset}
          style={{ transition: 'stroke-dashoffset 0.8s cubic-bezier(0.4,0,0.2,1)' }}
        />
      </svg>
      <div className="absolute text-center">
        <div className="text-3xl font-extrabold tracking-tight" style={{ color }}>
          {pct}%
        </div>
        <div className="text-[10px] font-semibold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>
          healthy
        </div>
      </div>
    </div>
  )
}
