import { createContext, useCallback, useContext, useState } from 'react'

const ToastContext = createContext(null)

let seq = 0

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const dismiss = useCallback((id) => {
    setToasts((list) => list.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (message, { type = 'info', duration = 4000 } = {}) => {
      const id = ++seq
      setToasts((list) => [...list, { id, message, type }])
      if (duration) setTimeout(() => dismiss(id), duration)
      return id
    },
    [dismiss]
  )

  const toast = {
    info: (m, o) => push(m, { ...o, type: 'info' }),
    success: (m, o) => push(m, { ...o, type: 'success' }),
    error: (m, o) => push(m, { ...o, type: 'error' }),
  }

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <ToastViewport toasts={toasts} dismiss={dismiss} />
    </ToastContext.Provider>
  )
}

const STYLES = {
  info: { icon: 'ℹ️', ring: 'border-l-brand-500' },
  success: { icon: '✅', ring: 'border-l-emerald-500' },
  error: { icon: '⚠️', ring: 'border-l-red-500' },
}

function ToastViewport({ toasts, dismiss }) {
  return (
    <div className="fixed bottom-5 right-5 z-[100] flex flex-col gap-3 w-[min(92vw,360px)]">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`animate-toast-in flex items-start gap-3 rounded-xl border border-l-4 ${STYLES[t.type].ring} px-4 py-3 shadow-lg`}
          style={{ background: 'var(--surface)', borderColor: 'var(--line)' }}
        >
          <span className="text-lg leading-none">{STYLES[t.type].icon}</span>
          <p className="flex-1 text-sm" style={{ color: 'var(--ink)' }}>
            {t.message}
          </p>
          <button
            onClick={() => dismiss(t.id)}
            className="text-lg leading-none opacity-50 hover:opacity-100"
            style={{ color: 'var(--muted)' }}
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}

export const useToast = () => useContext(ToastContext)
