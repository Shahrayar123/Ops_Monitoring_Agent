import { Logo } from '../components/Logo'
import { ThemeToggle } from '../components/ThemeToggle'

// Split-screen auth shell: a branded gradient panel with the pitch on the left,
// the form on the right. The left panel collapses on small screens.
export function AuthLayout({ children }) {
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      {/* Brand panel */}
      <div className="relative hidden overflow-hidden lg:block bg-gradient-to-br from-brand-900 via-brand-700 to-accent-600">
        <div className="absolute -right-16 -top-16 h-96 w-96 rounded-full bg-white/10 blur-2xl" />
        <div className="absolute bottom-0 left-0 h-80 w-80 rounded-full bg-accent-500/20 blur-3xl" />
        <div className="relative flex h-full flex-col justify-between p-12 text-white">
          <Logo size={48} />
          <div>
            <h1 className="text-4xl font-bold leading-tight tracking-tight">
              Cloudera clusters,
              <br />
              watched around the clock.
            </h1>
            <p className="mt-4 max-w-md text-white/80">
              Deterministic health checks across every host and service, with governed AI that
              explains incidents and recommends fixes — never guesses.
            </p>
            <ul className="mt-8 space-y-2.5 text-sm text-white/85">
              <li className="flex items-center gap-2">✓ Nine automated cluster checks</li>
              <li className="flex items-center gap-2">✓ AI incident analysis with a human in the loop</li>
              <li className="flex items-center gap-2">✓ Bring your own model — local or cloud</li>
            </ul>
          </div>
          <p className="text-xs text-white/60">© Blutech Consulting</p>
        </div>
      </div>

      {/* Form panel */}
      <div className="relative flex items-center justify-center p-6 sm:p-10">
        <div className="absolute right-5 top-5">
          <ThemeToggle />
        </div>
        <div className="w-full max-w-sm animate-fade-in">
          <div className="mb-8 lg:hidden">
            <Logo size={44} withWordmark />
          </div>
          {children}
        </div>
      </div>
    </div>
  )
}
