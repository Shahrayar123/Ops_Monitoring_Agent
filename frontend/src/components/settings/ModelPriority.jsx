import { useState } from 'react'
import { Button } from '../ui'
import { llmApi } from '../../lib/llmApi'
import { groupModelsByProvider } from '../ModelPicker'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'

const SLOT_LABELS = ['Default', '2nd — fallback', '3rd — fallback']

// The user's model fallback chain: up to 3 models, in order. Phase 5's AI tries
// the default first, then falls back down the chain if a model fails.
export function ModelPriority({ settings, onChange }) {
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState(false)

  const allowed = settings.models.filter((m) => m.allowed)
  const chain = settings.model_priority || []
  const byId = Object.fromEntries(settings.models.map((m) => [m.id, m]))
  const available = allowed.filter((m) => !chain.includes(m.id))

  async function save(next) {
    setBusy(true)
    try {
      onChange(await llmApi.setPriority(next))
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  const add = (id) => chain.length < 3 && save([...chain, id])
  const remove = (id) => save(chain.filter((x) => x !== id))
  const move = (i, dir) => {
    const next = [...chain]
    const j = i + dir
    if (j < 0 || j >= next.length) return
    ;[next[i], next[j]] = [next[j], next[i]]
    save(next)
  }

  async function testDefault() {
    if (!chain[0]) return
    setTesting(true)
    try {
      const r = await llmApi.testModel(chain[0])
      toast.success(`${r.message} Reply: "${r.reply}"`)
      onChange(await llmApi.getSettings())
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setTesting(false)
    }
  }

  return (
    <div>
      <div className="mb-3 flex items-center justify-between">
        <p className="text-xs" style={{ color: 'var(--muted)' }}>
          Pick up to 3 models in order. The AI uses your default first, and falls back to the next if one fails.
        </p>
        <Button variant="subtle" onClick={testDefault} loading={testing} disabled={!chain[0]}>⚡ Test default</Button>
      </div>

      {allowed.length === 0 ? (
        <p className="text-sm" style={{ color: 'var(--muted)' }}>Your administrator hasn't granted you any models yet.</p>
      ) : (
        <>
          {/* The ordered chain */}
          <div className="space-y-2">
            {chain.length === 0 && (
              <div className="rounded-xl border border-dashed p-4 text-center text-sm" style={{ borderColor: 'var(--line)', color: 'var(--faint)' }}>
                No models chosen yet — add one below to set your default.
              </div>
            )}
            {chain.map((id, i) => {
              const m = byId[id]
              return (
                <div key={id} className="flex items-center gap-3 rounded-xl border p-3" style={{ borderColor: i === 0 ? 'var(--brand-600)' : 'var(--line)', borderWidth: i === 0 ? 2 : 1 }}>
                  <span className="grid h-7 w-7 place-items-center rounded-full bg-brand-600 text-xs font-bold text-white">{i + 1}</span>
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-bold" style={{ color: 'var(--ink)' }}>{m?.label || id}</div>
                    <div className="text-xs" style={{ color: 'var(--faint)' }}>
                      {SLOT_LABELS[i]} · {m?.provider_label}
                      {m && !m.key_ready && <span className="ml-1 text-amber-600">⚠ needs key</span>}
                    </div>
                  </div>
                  <div className="flex items-center gap-1">
                    <IconBtn onClick={() => move(i, -1)} disabled={i === 0 || busy}>↑</IconBtn>
                    <IconBtn onClick={() => move(i, 1)} disabled={i === chain.length - 1 || busy}>↓</IconBtn>
                    <IconBtn onClick={() => remove(id)} disabled={busy} danger>×</IconBtn>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Add from available — grouped by provider */}
          {available.length > 0 && chain.length < 3 && (
            <div className="mt-4">
              <div className="mb-2 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>Add a model</div>
              <div className="space-y-2.5">
                {groupModelsByProvider(available).map((g) => (
                  <div key={g.provider}>
                    <div className="mb-1 text-[10px] font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>{g.label}</div>
                    <div className="flex flex-wrap gap-2">
                      {g.models.map((m) => (
                        <button
                          key={m.id}
                          onClick={() => add(m.id)}
                          disabled={busy}
                          className="rounded-lg border px-3 py-1.5 text-xs font-semibold transition hover:border-brand-400"
                          style={{ borderColor: 'var(--line)', color: 'var(--ink)' }}
                        >
                          + {m.label}
                          {!m.key_ready && <span className="ml-1 text-amber-600">⚠</span>}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function IconBtn({ onClick, disabled, danger, children }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="grid h-7 w-7 place-items-center rounded-lg border text-sm transition disabled:opacity-30"
      style={{ borderColor: 'var(--line)', color: danger ? '#ef4444' : 'var(--ink)' }}
    >
      {children}
    </button>
  )
}
