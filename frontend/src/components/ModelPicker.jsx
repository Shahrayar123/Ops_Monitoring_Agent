// Shared model selectors, grouped by provider. The catalog (GET /admin/catalog)
// returns each model with its `provider` + `provider_label`, so we group on that
// and show a provider header above each group — the nested "Provider -> models"
// structure, now that the roster spans Anthropic, OpenAI, Google, Grok, Groq,
// OpenRouter, and local Ollama.

// Provider display order (mirrors the backend's PROVIDER_ORDER). Anything not
// listed falls to the end, alphabetically by label.
const PROVIDER_ORDER = ['anthropic', 'openai', 'google', 'xai', 'groq', 'openrouter', 'ollama']

export function groupModelsByProvider(models) {
  const byProvider = new Map()
  for (const m of models) {
    if (!byProvider.has(m.provider)) {
      byProvider.set(m.provider, { provider: m.provider, label: m.provider_label || m.provider, models: [] })
    }
    byProvider.get(m.provider).models.push(m)
  }
  const groups = [...byProvider.values()]
  groups.sort((a, b) => {
    const ai = PROVIDER_ORDER.indexOf(a.provider)
    const bi = PROVIDER_ORDER.indexOf(b.provider)
    if (ai !== -1 && bi !== -1) return ai - bi
    if (ai !== -1) return -1
    if (bi !== -1) return 1
    return a.label.localeCompare(b.label)
  })
  return groups
}

// Multi-select: grouped checkboxes with a provider header per group. Used where
// an admin grants which models a user (or plan) may use.
export function GroupedModelCheckboxes({ models, selected, onToggle }) {
  const groups = groupModelsByProvider(models)
  return (
    <div className="rounded-xl border" style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}>
      {groups.map((g, i) => (
        <div key={g.provider} className={i > 0 ? 'border-t' : ''} style={{ borderColor: 'var(--line)' }}>
          <div className="px-3 pb-1 pt-2.5 text-[11px] font-bold uppercase tracking-wide" style={{ color: 'var(--faint)' }}>
            {g.label}
          </div>
          <div className="flex flex-col gap-1.5 px-3 pb-2.5">
            {g.models.map((m) => (
              <label key={m.id} className="flex cursor-pointer items-center gap-2.5 text-sm" style={{ color: 'var(--ink)' }}>
                <input
                  type="checkbox" checked={selected.includes(m.id)}
                  onChange={() => onToggle(m.id)}
                  className="h-4 w-4 shrink-0 accent-brand-600"
                />
                <span className="font-medium">{m.label}</span>
              </label>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
