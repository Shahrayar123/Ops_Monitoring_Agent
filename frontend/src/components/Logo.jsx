import logo from '../assets/logo.jpg'

// The company logo in a white rounded tile, so it reads cleanly on both the
// brand-gradient login panel and the app's light/dark surfaces.
export function Logo({ size = 40, withWordmark = false }) {
  return (
    <div className="flex items-center gap-3">
      <div
        className="flex items-center justify-center rounded-xl bg-white shadow-sm ring-1 ring-black/5"
        style={{ width: size, height: size, padding: size * 0.14 }}
      >
        <img src={logo} alt="Blutech Consulting" className="h-full w-auto object-contain" />
      </div>
      {withWordmark && (
        <div className="leading-tight">
          <div className="text-sm font-bold" style={{ color: 'var(--ink)' }}>
            Cloudera Ops
          </div>
          <div className="text-[11px]" style={{ color: 'var(--faint)' }}>
            by Blutech Consulting
          </div>
        </div>
      )}
    </div>
  )
}
