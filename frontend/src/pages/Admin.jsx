import { useState } from 'react'
import { PageHeader } from '../components/ui'
import { TenantManager } from '../components/admin/TenantManager'
import { PlansManager } from '../components/admin/PlansManager'
import { UsageDashboard } from '../components/admin/UsageDashboard'
import { UserManager } from '../components/admin/UserManager'

const TABS = [
  { key: 'clusters', label: 'Clusters' },
  { key: 'plans', label: 'Plans' },
  { key: 'usage', label: 'Usage' },
  { key: 'users', label: 'Users' },
]

export default function Admin() {
  const [tab, setTab] = useState('clusters')

  return (
    <>
      <PageHeader title="Admin" subtitle="Clusters, data sources, plans, and usage." />

      <div className="mb-6 flex gap-1 rounded-xl border p-1" style={{ borderColor: 'var(--line)', width: 'max-content' }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${tab === t.key ? 'bg-brand-600 text-white' : ''}`}
            style={tab === t.key ? undefined : { color: 'var(--muted)' }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'clusters' && <TenantManager />}
      {tab === 'plans' && <PlansManager />}
      {tab === 'usage' && <UsageDashboard />}
      {tab === 'users' && <UserManager />}
    </>
  )
}
