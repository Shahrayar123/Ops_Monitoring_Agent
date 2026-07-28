// Small shared primitives so pages stay consistent and short.

export function Button({ variant = 'primary', className = '', loading, children, ...props }) {
  const base =
    'inline-flex items-center justify-center gap-2 rounded-xl font-semibold text-sm px-4 py-2.5 transition ' +
    'disabled:opacity-60 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-brand-400/60'
  const variants = {
    primary: 'bg-brand-600 hover:bg-brand-700 text-white shadow-sm',
    ghost: 'hover:bg-black/5 dark:hover:bg-white/5',
    subtle: 'border',
    danger: 'bg-red-600 hover:bg-red-700 text-white',
  }
  const style = variant === 'subtle' ? { borderColor: 'var(--line)', color: 'var(--ink)' } : undefined
  return (
    <button className={`${base} ${variants[variant]} ${className}`} style={style} disabled={loading || props.disabled} {...props}>
      {loading && <Spinner />}
      {children}
    </button>
  )
}

export function Input({ label, hint, error, className = '', ...props }) {
  return (
    <label className="block">
      {label && (
        <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>
          {label}
        </span>
      )}
      <input
        className={`w-full rounded-xl border px-3.5 py-2.5 text-sm outline-none transition
          focus:ring-2 focus:ring-brand-400/50 focus:border-brand-400 ${className}`}
        style={{ background: 'var(--surface-2)', borderColor: error ? '#ef4444' : 'var(--line)', color: 'var(--ink)' }}
        {...props}
      />
      {error ? (
        <span className="mt-1 block text-xs text-red-500">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-xs" style={{ color: 'var(--faint)' }}>
          {hint}
        </span>
      ) : null}
    </label>
  )
}

export function Spinner({ className = 'h-4 w-4' }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-90" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  )
}

export function Card({ className = '', children, ...props }) {
  return (
    <div className={`card p-5 ${className}`} {...props}>
      {children}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="mb-6 flex items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-bold tracking-tight" style={{ color: 'var(--ink)' }}>
          {title}
        </h1>
        {subtitle && (
          <p className="mt-1 text-sm" style={{ color: 'var(--muted)' }}>
            {subtitle}
          </p>
        )}
      </div>
      {actions}
    </div>
  )
}
