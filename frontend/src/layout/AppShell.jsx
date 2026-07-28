import { useState } from 'react'
import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import { Logo } from '../components/Logo'
import { ThemeToggle } from '../components/ThemeToggle'
import { ForcePasswordChange } from '../components/ForcePasswordChange'
import { useAuth } from '../lib/auth'
import { useToast } from '../lib/toast'

const NAV = [
  { to: '/dashboard', label: 'Dashboard', icon: '📊' },
  { to: '/settings', label: 'Settings', icon: '⚙️' },
  { to: '/admin', label: 'Admin', icon: '🛡️', adminOnly: true },
]

export function AppShell() {
  const { user, isAdmin, logout } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const [mobileNav, setMobileNav] = useState(false)

  async function onLogout() {
    await logout()
    toast.info('Signed out.')
    navigate('/login', { replace: true })
  }

  const items = NAV.filter((n) => !n.adminOnly || isAdmin)

  return (
    <div className="flex min-h-screen">
      <ForcePasswordChange />
      {/* Sidebar */}
      <aside
        className={`fixed z-40 flex h-screen w-64 flex-col border-r transition-transform lg:static lg:translate-x-0 ${
          mobileNav ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ background: 'var(--surface)', borderColor: 'var(--line)' }}
      >
        <div className="flex h-16 items-center border-b px-5" style={{ borderColor: 'var(--line)' }}>
          <Logo size={38} withWordmark />
        </div>
        <nav className="flex-1 space-y-1 p-3">
          {items.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setMobileNav(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-xl px-3.5 py-2.5 text-sm font-medium transition ${
                  isActive ? 'bg-brand-600 text-white shadow-sm' : 'hover:bg-black/5 dark:hover:bg-white/5'
                }`
              }
              style={({ isActive }) => (isActive ? undefined : { color: 'var(--muted)' })}
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-4 text-xs" style={{ borderColor: 'var(--line)', color: 'var(--faint)' }}>
          Cloudera Ops · v2.0
        </div>
      </aside>

      {mobileNav && (
        <div className="fixed inset-0 z-30 bg-black/40 lg:hidden" onClick={() => setMobileNav(false)} />
      )}

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        {/* Topbar */}
        <header
          className="sticky top-0 z-20 flex h-16 items-center justify-between gap-3 border-b px-4 sm:px-6 backdrop-blur"
          style={{ background: 'color-mix(in srgb, var(--surface) 80%, transparent)', borderColor: 'var(--line)' }}
        >
          <button
            className="grid h-9 w-9 place-items-center rounded-lg border lg:hidden"
            style={{ borderColor: 'var(--line)', color: 'var(--ink)' }}
            onClick={() => setMobileNav(true)}
            aria-label="Open navigation"
          >
            ☰
          </button>
          <div className="flex-1" />
          <ThemeToggle />

          {/* User menu */}
          <div className="relative">
            <button
              onClick={() => setMenuOpen((o) => !o)}
              className="flex items-center gap-2 rounded-xl border px-2.5 py-1.5"
              style={{ borderColor: 'var(--line)', color: 'var(--ink)' }}
            >
              <span className="grid h-7 w-7 place-items-center rounded-full bg-brand-600 text-xs font-bold text-white">
                {(user?.full_name || user?.email || '?').charAt(0).toUpperCase()}
              </span>
              <span className="hidden text-sm font-medium sm:block">{user?.full_name || user?.email}</span>
              <span className="text-xs" style={{ color: 'var(--faint)' }}>▾</span>
            </button>
            {menuOpen && (
              <>
                <div className="fixed inset-0 z-10" onClick={() => setMenuOpen(false)} />
                <div
                  className="absolute right-0 z-20 mt-2 w-56 overflow-hidden rounded-xl border shadow-lg animate-fade-in"
                  style={{ background: 'var(--surface)', borderColor: 'var(--line)' }}
                >
                  <div className="border-b px-4 py-3" style={{ borderColor: 'var(--line)' }}>
                    <div className="text-sm font-semibold" style={{ color: 'var(--ink)' }}>
                      {user?.full_name || 'Account'}
                    </div>
                    <div className="truncate text-xs" style={{ color: 'var(--faint)' }}>
                      {user?.email}
                    </div>
                    <span className="mt-1.5 inline-block rounded-full bg-brand-50 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">
                      {user?.role}
                    </span>
                  </div>
                  <button
                    onClick={() => {
                      setMenuOpen(false)
                      navigate('/settings')
                    }}
                    className="block w-full px-4 py-2.5 text-left text-sm hover:bg-black/5 dark:hover:bg-white/5"
                    style={{ color: 'var(--ink)' }}
                  >
                    ⚙️ Settings
                  </button>
                  <button
                    onClick={onLogout}
                    className="block w-full px-4 py-2.5 text-left text-sm text-red-500 hover:bg-red-500/10"
                  >
                    ⏻ Sign out
                  </button>
                </div>
              </>
            )}
          </div>
        </header>

        {/* Routed page */}
        <main className="flex-1 p-4 sm:p-6 lg:p-8">
          <div className="mx-auto max-w-7xl animate-fade-in">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
