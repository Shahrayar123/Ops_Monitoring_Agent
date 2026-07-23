import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Button, Card, Input, Spinner } from '../ui'
import { api } from '../../lib/api'
import { plansApi, userAdminApi } from '../../lib/llmApi'
import { monitoringApi } from '../../lib/monitoringApi'
import { GroupedModelCheckboxes } from '../ModelPicker'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'

// The Users tab: list users, invite new ones (with credentials shown on screen),
// and control each user's model access + call/token limits.
const STATUS_LABEL = {
  active: { text: '● Active', color: 'text-emerald-500' },
  deletion_requested: { text: '● Active', color: 'text-emerald-500' },
  deleted_recoverable: { text: '◐ Deleted (recoverable)', color: 'text-amber-500' },
  recovery_requested: { text: '◐ Deleted (recoverable)', color: 'text-amber-500' },
  dormant: { text: '● Dormant', color: 'text-red-500' },
}

export function UserManager() {
  const toast = useToast()
  const [inviting, setInviting] = useState(false)
  const [editing, setEditing] = useState(null) // user id
  const [busyId, setBusyId] = useState(null) // user id currently mid-action
  const users = useQuery({ queryKey: ['admin', 'users'], queryFn: async () => (await api.get('/admin/users')).data })
  const plans = useQuery({ queryKey: ['plans'], queryFn: plansApi.list })
  const catalog = useQuery({ queryKey: ['catalog'], queryFn: plansApi.catalog })
  const tenants = useQuery({ queryKey: ['tenants'], queryFn: monitoringApi.listTenants })

  if (users.isLoading || catalog.isLoading) return <Card><Spinner /></Card>

  async function runAction(u, actionFn, confirmMsg, successMsg) {
    if (confirmMsg && !confirm(confirmMsg)) return
    setBusyId(u.id)
    try {
      await actionFn(u.id)
      toast.success(successMsg)
      users.refetch()
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = (u) => runAction(
    u, userAdminApi.remove,
    `Permanently delete "${u.email}"? This immediately removes their account, cluster access, and usage history — it cannot be undone.`,
    'User permanently deleted.',
  )
  const handleAccept = (u) => runAction(
    u, userAdminApi.acceptDeletion,
    `Accept the deletion request for "${u.email}"? Their account will be deactivated immediately, with a 30-day recovery window before it becomes permanently dormant.`,
    'Deletion accepted — account deactivated with a 30-day recovery window.',
  )
  const handleReject = (u) => runAction(u, userAdminApi.rejectDeletion, null, 'Deletion request rejected — account stays active.')
  const handleApproveRecovery = (u) => runAction(
    u, userAdminApi.approveRecovery,
    `Restore "${u.email}"'s account to normal?`,
    'Account restored.',
  )
  const handleRejectRecovery = (u) => runAction(u, userAdminApi.rejectRecovery, null, 'Recovery request rejected — account stays deleted (recoverable).')

  return (
    <>
      <div className="mb-4 flex justify-end">
        <Button onClick={() => setInviting(true)}>+ Invite user</Button>
      </div>

      <Card>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide" style={{ color: 'var(--faint)' }}>
                <th className="pb-2">Email</th><th className="pb-2">Role</th><th className="pb-2">Plan</th><th className="pb-2">Status</th><th className="pb-2"></th>
              </tr>
            </thead>
            <tbody>
              {users.data.map((u) => {
                const status = u.account_status || 'active'
                const busy = busyId === u.id
                const statusLabel = STATUS_LABEL[status] || STATUS_LABEL.active
                return (
                  <tr key={u.id} className="border-t" style={{ borderColor: 'var(--line)' }}>
                    <td className="py-2.5" style={{ color: 'var(--ink)' }}>
                      {u.email}
                      {u.must_change_password && <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-bold text-amber-700 dark:bg-amber-500/15">PENDING</span>}
                      {status === 'deletion_requested' && <span className="ml-2 rounded bg-red-100 px-1.5 py-0.5 text-[10px] font-bold text-red-700 dark:bg-red-500/15 dark:text-red-400">DELETION REQUESTED</span>}
                      {status === 'recovery_requested' && <span className="ml-2 rounded bg-blue-100 px-1.5 py-0.5 text-[10px] font-bold text-blue-700 dark:bg-blue-500/15 dark:text-blue-400">RECOVERY REQUESTED</span>}
                      {status === 'deleted_recoverable' && u.recoverable_until && (
                        <span className="ml-2 text-[10px]" style={{ color: 'var(--faint)' }}>
                          recoverable until {new Date(u.recoverable_until).toLocaleDateString()}
                        </span>
                      )}
                    </td>
                    <td className="py-2.5">
                      <span className="rounded-full bg-brand-50 px-2 py-0.5 text-[11px] font-bold uppercase text-brand-700 dark:bg-brand-500/15 dark:text-brand-300">{u.role}</span>
                    </td>
                    <td className="py-2.5" style={{ color: 'var(--muted)' }}>{u.plan?.name || '—'}</td>
                    <td className="py-2.5"><span className={statusLabel.color}>{statusLabel.text}</span></td>
                    <td className="py-2.5 text-right whitespace-nowrap">
                      {status === 'deletion_requested' && (
                        <>
                          <button onClick={() => handleAccept(u)} disabled={busy} className="text-xs font-semibold text-emerald-600 disabled:opacity-50">Accept</button>
                          <button onClick={() => handleReject(u)} disabled={busy} className="ml-3 text-xs font-semibold" style={{ color: 'var(--muted)' }}>Reject</button>
                        </>
                      )}
                      {status === 'recovery_requested' && (
                        <>
                          <button onClick={() => handleApproveRecovery(u)} disabled={busy} className="text-xs font-semibold text-emerald-600 disabled:opacity-50">Approve recovery</button>
                          <button onClick={() => handleRejectRecovery(u)} disabled={busy} className="ml-3 text-xs font-semibold" style={{ color: 'var(--muted)' }}>Reject recovery</button>
                        </>
                      )}
                      {status === 'deleted_recoverable' && (
                        <button
                          onClick={() => handleApproveRecovery(u)} disabled={busy}
                          className="text-xs font-semibold text-emerald-600 disabled:opacity-50"
                          title="Restore this account now, without waiting for the user to request recovery"
                        >
                          Restore now
                        </button>
                      )}
                      {(status === 'active' || status === 'deletion_requested') && (
                        <button onClick={() => setEditing(u.id)} className={status === 'deletion_requested' ? 'ml-3 text-xs font-semibold text-brand-600' : 'text-xs font-semibold text-brand-600'}>
                          Access, clusters &amp; limits
                        </button>
                      )}
                      {u.role === 'admin' ? (
                        <span className="ml-3 text-xs font-semibold" style={{ color: 'var(--faint)' }} title="Admin accounts cannot be deleted">Delete</span>
                      ) : status === 'active' ? (
                        <button onClick={() => handleDelete(u)} disabled={busy} className="ml-3 text-xs font-semibold text-red-500 disabled:opacity-50">
                          {busy ? 'Deleting…' : 'Delete'}
                        </button>
                      ) : (status === 'deleted_recoverable' || status === 'dormant') && (
                        <button onClick={() => handleDelete(u)} disabled={busy} className="ml-3 text-xs font-semibold text-red-500 disabled:opacity-50" title="Permanently purge this account now, instead of waiting out the recovery window">
                          {busy ? 'Purging…' : 'Purge now'}
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {inviting && (
        <InviteModal
          plans={plans.data || []} catalog={catalog.data} tenants={tenants.data || []}
          onClose={() => setInviting(false)} onDone={() => { users.refetch() }}
        />
      )}
      {editing && (
        <AccessModal userId={editing} catalog={catalog.data} onClose={() => setEditing(null)} onSaved={() => users.refetch()} />
      )}
    </>
  )
}

function LimitFields({ form, set }) {
  const F = [
    ['daily_call_limit', 'Calls / day'],
    ['monthly_call_limit', 'Calls / month'],
    ['daily_token_limit', 'Tokens / day'],
    ['monthly_token_limit', 'Tokens / month'],
  ]
  return (
    <div className="grid grid-cols-2 gap-3">
      {F.map(([k, label]) => (
        <Input
          key={k} label={label} type="number" placeholder="inherit"
          value={form[k] ?? ''} hint="blank = plan default · 0 = unlimited"
          onChange={(e) => set(k, e.target.value === '' ? null : Number(e.target.value))}
        />
      ))}
    </div>
  )
}

// Allowed-models picker: grouped by provider (Anthropic, OpenAI, Google, Grok,
// Groq, OpenRouter, local Ollama). See components/ModelPicker.jsx.
const ModelChips = GroupedModelCheckboxes

function InviteModal({ plans, catalog, tenants, onClose, onDone }) {
  const toast = useToast()
  const [form, setForm] = useState({ email: '', full_name: '', role: 'user', plan_id: plans[0]?.id || null, allowed_models: [], tenant_slugs: [], daily_call_limit: null, monthly_call_limit: null, daily_token_limit: null, monthly_token_limit: null })
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const toggle = (id) => set('allowed_models', form.allowed_models.includes(id) ? form.allowed_models.filter((x) => x !== id) : [...form.allowed_models, id])
  const toggleTenant = (slug) => set('tenant_slugs', form.tenant_slugs.includes(slug) ? form.tenant_slugs.filter((x) => x !== slug) : [...form.tenant_slugs, slug])

  async function invite() {
    setBusy(true)
    try {
      const r = await userAdminApi.create({ ...form, plan_id: form.plan_id ? Number(form.plan_id) : null })
      setResult(r)
      onDone()
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal onClose={onClose} title={result ? 'User invited' : 'Invite a user'}>
      {result ? (
        <div className="space-y-4">
          <p className="text-sm" style={{ color: 'var(--muted)' }}>{result.message}</p>
          <div className="rounded-xl border p-4 text-sm" style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}>
            <Row k="Email" v={result.email} />
            <Row k="Temporary password" v={result.temp_password} mono />
            <Row k="Sign-in link" v={result.invite_link} />
          </div>
          <p className="text-xs" style={{ color: 'var(--faint)' }}>⚠ This password is shown only once. Copy it now and share it securely. The user must change it on first sign-in.</p>
          <div className="flex justify-end"><Button onClick={onClose}>Done</Button></div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Email" type="email" value={form.email} onChange={(e) => set('email', e.target.value)} />
            <Input label="Full name" value={form.full_name} onChange={(e) => set('full_name', e.target.value)} />
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>Role</span>
              <select value={form.role} onChange={(e) => set('role', e.target.value)} className="w-full rounded-xl border px-3.5 py-2.5 text-sm" style={{ background: 'var(--surface-2)', borderColor: 'var(--line)', color: 'var(--ink)' }}>
                <option value="user">User</option>
                <option value="admin">Admin</option>
              </select>
            </label>
            <label className="block">
              <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>Plan (defaults)</span>
              <select value={form.plan_id || ''} onChange={(e) => set('plan_id', e.target.value)} className="w-full rounded-xl border px-3.5 py-2.5 text-sm" style={{ background: 'var(--surface-2)', borderColor: 'var(--line)', color: 'var(--ink)' }}>
                <option value="">— none —</option>
                {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </label>
          </div>
          <div>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>Allowed models <span className="font-normal" style={{ color: 'var(--faint)' }}>(blank = inherit from plan)</span></span>
            <ModelChips models={catalog.models} selected={form.allowed_models} onToggle={toggle} />
          </div>
          {form.role !== 'admin' && (
            <div>
              <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>
                Clusters <span className="font-normal" style={{ color: 'var(--faint)' }}>(which JSON/API data sources this user can see — optional, can also be set later)</span>
              </span>
              {tenants.length ? (
                <TenantCheckboxList tenants={tenants} selected={form.tenant_slugs} onToggle={toggleTenant} />
              ) : (
                <p className="text-xs" style={{ color: 'var(--faint)' }}>No clusters exist yet — create one in the Clusters tab first.</p>
              )}
            </div>
          )}
          <div>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>Usage limits</span>
            <LimitFields form={form} set={set} />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="subtle" onClick={onClose}>Cancel</Button>
            <Button onClick={invite} loading={busy} disabled={!form.email}>Create &amp; get invite</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function AccessModal({ userId, catalog, onClose, onSaved }) {
  const toast = useToast()
  const detail = useQuery({ queryKey: ['user-detail', userId], queryFn: () => userAdminApi.detail(userId) })
  const [form, setForm] = useState(null)
  const [busy, setBusy] = useState(false)

  const d = detail.data
  if (d && form === null) {
    setForm({
      allowed_models: d.allowed_models, daily_call_limit: d.daily_call_limit, monthly_call_limit: d.monthly_call_limit,
      daily_token_limit: d.daily_token_limit, monthly_token_limit: d.monthly_token_limit,
    })
  }
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const toggle = (id) => set('allowed_models', form.allowed_models.includes(id) ? form.allowed_models.filter((x) => x !== id) : [...form.allowed_models, id])

  async function save() {
    setBusy(true)
    try {
      await userAdminApi.setAccess(userId, form)
      toast.success('Access updated.')
      onSaved()
      onClose()
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal onClose={onClose} title={d ? `Access — ${d.email}` : 'Access'}>
      {!d || !form ? <Spinner /> : (
        <div className="space-y-4">
          <div className="rounded-lg px-3 py-2 text-xs" style={{ background: 'var(--surface-2)', color: 'var(--muted)' }}>
            Effective: <b>{d.effective_allowed_models.length}</b> models · {d.effective_daily_calls || '∞'} calls/day · {d.effective_daily_tokens ? d.effective_daily_tokens.toLocaleString() : '∞'} tokens/day
            {d.model_priority.length > 0 && <> · using {d.model_priority.join(' → ')}</>}
          </div>
          <div>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>Allowed models <span className="font-normal" style={{ color: 'var(--faint)' }}>(blank = inherit from plan)</span></span>
            <ModelChips models={catalog.models} selected={form.allowed_models} onToggle={toggle} />
          </div>
          <div>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>Usage limits</span>
            <LimitFields form={form} set={set} />
          </div>
          <div className="border-t pt-4" style={{ borderColor: 'var(--line)' }}>
            <span className="mb-1.5 block text-sm font-medium" style={{ color: 'var(--ink)' }}>
              Clusters <span className="font-normal" style={{ color: 'var(--faint)' }}>(which JSON/API data sources appear on this user's dashboard)</span>
            </span>
            <ClusterAccess userId={userId} />
          </div>

          <div className="flex justify-end gap-2 border-t pt-4" style={{ borderColor: 'var(--line)' }}>
            <Button variant="subtle" onClick={onClose}>Cancel</Button>
            <Button onClick={save} loading={busy}>Save access</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

// Checkbox list for cluster access: the admin ticks whichever clusters this
// user should see and saves once (a previous toggle-chip design that saved
// per-click was confusing — the selected chip's label became hard to read,
// and there was no visible "did this actually save?" signal).
function ClusterAccess({ userId }) {
  const toast = useToast()
  const [selected, setSelected] = useState(null) // Set of slugs; null until loaded
  const [saving, setSaving] = useState(false)
  const tenants = useQuery({ queryKey: ['tenants'], queryFn: monitoringApi.listTenants })
  const linked = useQuery({ queryKey: ['user-clusters', userId], queryFn: () => userAdminApi.clusters(userId) })

  if (linked.data && selected === null) {
    setSelected(new Set(linked.data.map((t) => t.slug)))
  }

  if (tenants.isLoading || linked.isLoading || selected === null) return <Spinner />
  if (!tenants.data?.length) {
    return <p className="text-xs" style={{ color: 'var(--faint)' }}>No clusters exist yet — create one in the Clusters tab first.</p>
  }

  const originalSlugs = new Set((linked.data || []).map((t) => t.slug))
  const dirty = selected.size !== originalSlugs.size || [...selected].some((s) => !originalSlugs.has(s))

  function toggle(slug) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(slug)) next.delete(slug)
      else next.add(slug)
      return next
    })
  }

  async function save() {
    setSaving(true)
    try {
      await userAdminApi.setClusters(userId, [...selected])
      toast.success('Cluster access saved — visible on the user\'s dashboard now.')
      await linked.refetch()
    } catch (err) {
      toast.error(normalizeError(err).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <TenantCheckboxList tenants={tenants.data} selected={selected} onToggle={toggle} disabled={saving} />
      <div className="flex items-center justify-between">
        <span className="text-xs" style={{ color: 'var(--faint)' }}>{dirty ? 'Unsaved changes' : 'Up to date'}</span>
        <Button onClick={save} loading={saving} disabled={!dirty}>Save clusters</Button>
      </div>
    </div>
  )
}

// Shared checkbox-list presentation for cluster selection. `selected` accepts
// either a Set or an array of slugs (InviteModal uses a plain array in local
// form state; ClusterAccess uses a Set of the currently-ticked slugs).
function TenantCheckboxList({ tenants, selected, onToggle, disabled }) {
  const selectedSet = selected instanceof Set ? selected : new Set(selected)
  return (
    <div className="flex flex-col gap-2 rounded-xl border p-3" style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}>
      {tenants.map((t) => (
        <label key={t.slug} className="flex cursor-pointer items-center gap-2.5 text-sm" style={{ color: 'var(--ink)' }}>
          <input
            type="checkbox" checked={selectedSet.has(t.slug)} disabled={disabled}
            onChange={() => onToggle(t.slug)}
            className="h-4 w-4 shrink-0 accent-brand-600"
          />
          <span className="font-medium">{t.display_name}</span>
          <span className="text-xs" style={{ color: 'var(--faint)' }}>({t.slug})</span>
        </label>
      ))}
    </div>
  )
}

function Modal({ title, onClose, children }) {
  // Rendered through a portal to <body> so it's positioned against the viewport,
  // never trapped by a transformed page ancestor.
  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50 p-4" onClick={onClose}>
      <div className="card max-h-[88vh] w-full max-w-2xl overflow-auto p-6 animate-fade-in" onClick={(e) => e.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-bold" style={{ color: 'var(--ink)' }}>{title}</h3>
          <button onClick={onClose} className="text-xl" style={{ color: 'var(--faint)' }}>×</button>
        </div>
        {children}
      </div>
    </div>,
    document.body
  )
}

function Row({ k, v, mono }) {
  return (
    <div className="flex items-center justify-between border-b py-1.5 last:border-0" style={{ borderColor: 'var(--line)' }}>
      <span style={{ color: 'var(--faint)' }}>{k}</span>
      <span className={mono ? 'font-mono font-bold' : ''} style={{ color: 'var(--ink)' }}>{v}</span>
    </div>
  )
}
