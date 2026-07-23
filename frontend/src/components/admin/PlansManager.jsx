import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button, Card, Input, Spinner } from '../ui'
import { plansApi } from '../../lib/llmApi'
import { GroupedModelCheckboxes } from '../ModelPicker'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'

const BLANK = {
  name: '', description: '', allowed_models: [], max_context_tokens: 8192,
  allowed_cloudera_versions: [], daily_api_limit: 0, monthly_api_limit: 0, is_active: true,
}

export function PlansManager() {
  const toast = useToast()
  const [editing, setEditing] = useState(null) // plan object or BLANK for new
  const plansQ = useQuery({ queryKey: ['plans'], queryFn: plansApi.list })
  const catalogQ = useQuery({ queryKey: ['catalog'], queryFn: plansApi.catalog })

  async function remove(plan) {
    if (!confirm(`Delete plan "${plan.name}"?`)) return
    try {
      await plansApi.remove(plan.id)
      toast.success('Plan deleted.')
      plansQ.refetch()
    } catch (err) {
      toast.error(normalizeError(err).message)
    }
  }

  if (plansQ.isLoading || catalogQ.isLoading) return <Spinner />

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      <div className="space-y-3">
        {plansQ.data.map((p) => (
          <Card key={p.id}>
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h4 className="text-base font-bold" style={{ color: 'var(--ink)' }}>{p.name}</h4>
                  {!p.is_active && <span className="text-xs text-red-500">inactive</span>}
                </div>
                <p className="mt-0.5 text-xs" style={{ color: 'var(--muted)' }}>{p.description || 'No description'}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {p.allowed_models.map((m) => (
                    <span key={m} className="rounded-md bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">{m}</span>
                  ))}
                </div>
                <div className="mt-2 text-xs" style={{ color: 'var(--faint)' }}>
                  {(p.max_context_tokens / 1000).toLocaleString()}K context · {p.daily_api_limit || '∞'}/day · {p.monthly_api_limit || '∞'}/mo · CDP {p.allowed_cloudera_versions.join(', ') || 'any'}
                </div>
              </div>
              <div className="flex gap-2">
                <button onClick={() => setEditing(p)} className="text-xs font-semibold text-brand-600">Edit</button>
                <button onClick={() => remove(p)} className="text-xs font-semibold text-red-500">Delete</button>
              </div>
            </div>
          </Card>
        ))}
        <Button variant="subtle" onClick={() => setEditing({ ...BLANK })}>+ New plan</Button>
      </div>

      {editing && (
        <PlanEditor
          plan={editing}
          catalog={catalogQ.data}
          onClose={() => setEditing(null)}
          onSaved={() => { setEditing(null); plansQ.refetch() }}
        />
      )}
    </div>
  )
}

function PlanEditor({ plan, catalog, onClose, onSaved }) {
  const toast = useToast()
  const [form, setForm] = useState(plan)
  const [busy, setBusy] = useState(false)
  const isNew = !plan.id
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  function toggle(list, key, value) {
    const cur = form[key]
    set(key, cur.includes(value) ? cur.filter((x) => x !== value) : [...cur, value])
  }

  async function save() {
    setBusy(true)
    try {
      const body = {
        ...form,
        max_context_tokens: Number(form.max_context_tokens),
        daily_api_limit: Number(form.daily_api_limit),
        monthly_api_limit: Number(form.monthly_api_limit),
      }
      if (isNew) await plansApi.create(body)
      else await plansApi.update(plan.id, body)
      toast.success('Plan saved.')
      onSaved()
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card className="h-max lg:sticky lg:top-20">
      <div className="mb-3 flex items-center justify-between">
        <h4 className="text-base font-bold" style={{ color: 'var(--ink)' }}>{isNew ? 'New plan' : `Edit ${plan.name}`}</h4>
        <button onClick={onClose} className="text-xl" style={{ color: 'var(--faint)' }}>×</button>
      </div>
      <div className="space-y-4">
        <Input label="Name" value={form.name} onChange={(e) => set('name', e.target.value)} />
        <Input label="Description" value={form.description} onChange={(e) => set('description', e.target.value)} />

        <Field label="Allowed models">
          <GroupedModelCheckboxes
            models={catalog.models} selected={form.allowed_models}
            onToggle={(id) => toggle('m', 'allowed_models', id)}
          />
        </Field>

        <Field label="Allowed Cloudera versions">
          <CheckboxList
            items={catalog.cloudera_versions} selected={form.allowed_cloudera_versions}
            onToggle={(v) => toggle('v', 'allowed_cloudera_versions', v)}
          />
        </Field>

        <div className="grid grid-cols-3 gap-3">
          <Input label="Context (tokens)" type="number" value={form.max_context_tokens} onChange={(e) => set('max_context_tokens', e.target.value)} />
          <Input label="Daily limit" type="number" value={form.daily_api_limit} onChange={(e) => set('daily_api_limit', e.target.value)} hint="0 = ∞" />
          <Input label="Monthly limit" type="number" value={form.monthly_api_limit} onChange={(e) => set('monthly_api_limit', e.target.value)} hint="0 = ∞" />
        </div>

        <label className="flex items-center gap-2 text-sm" style={{ color: 'var(--ink)' }}>
          <input type="checkbox" checked={form.is_active} onChange={(e) => set('is_active', e.target.checked)} /> Active
        </label>

        <div className="flex justify-end gap-2">
          <Button variant="subtle" onClick={onClose}>Cancel</Button>
          <Button onClick={save} loading={busy}>Save plan</Button>
        </div>
      </div>
    </Card>
  )
}

function Field({ label, children }) {
  return (
    <div>
      <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>{label}</span>
      {children}
    </div>
  )
}

// Checkbox list — not toggle chips, whose selected-state label went unreadable
// (same issue fixed for the user-access model/cluster pickers in UserManager.jsx).
function CheckboxList({ items, selected, onToggle, getLabel = (i) => i, getValue = (i) => i }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border p-3" style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}>
      {items.map((item) => {
        const value = getValue(item)
        return (
          <label key={value} className="flex cursor-pointer items-center gap-2.5 text-sm" style={{ color: 'var(--ink)' }}>
            <input
              type="checkbox" checked={selected.includes(value)}
              onChange={() => onToggle(value)}
              className="h-4 w-4 shrink-0 accent-brand-600"
            />
            <span className="font-medium">{getLabel(item)}</span>
          </label>
        )
      })}
    </div>
  )
}
