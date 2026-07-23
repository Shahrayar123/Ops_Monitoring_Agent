import { useTheme } from '../lib/theme'

export function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const dark = theme === 'dark'
  return (
    <button
      onClick={toggle}
      title={dark ? 'Switch to light mode' : 'Switch to dark mode'}
      aria-label="Toggle theme"
      className="grid h-9 w-9 place-items-center rounded-lg border transition hover:scale-105"
      style={{ borderColor: 'var(--line)', background: 'var(--surface)', color: 'var(--ink)' }}
    >
      <span className="text-base">{dark ? '☀️' : '🌙'}</span>
    </button>
  )
}
