import { useRef, useState } from 'react'
import { FILE_TYPES, tenantAdminApi } from '../../lib/tenantAdminApi'
import { useToast } from '../../lib/toast'
import { normalizeError } from '../../lib/api'
import { Spinner } from '../ui'

// One drop row per Cloudera export file type. Files map unambiguously to their
// type (no guessing): drop or pick a file on the "Disk metrics" row and it is
// validated + stored as disk.json. Validation runs the real engine parser, so
// a green row means "the checks can actually read this".
export function FileUploadManager({ tenant, onChange }) {
  const filesByType = {}
  for (const f of tenant.files || []) filesByType[f.file_type] = f
  const coverage = tenant.coverage

  return (
    <div>
      {coverage && (
        <div
          className="mb-4 rounded-xl px-4 py-2.5 text-sm font-medium"
          style={{
            background: coverage.ready ? 'rgba(34,197,94,0.1)' : 'rgba(245,158,11,0.1)',
            color: coverage.ready ? '#15803d' : '#b45309',
          }}
        >
          {coverage.ready
            ? '✅ All required files present — this cluster is ready to monitor.'
            : `⏳ Missing required files: ${coverage.missing_required.join(', ')}`}
        </div>
      )}
      <div className="space-y-2">
        {FILE_TYPES.map((ft) => (
          <FileRow key={ft.key} tenant={tenant} ft={ft} existing={filesByType[ft.key]} onChange={onChange} />
        ))}
      </div>
    </div>
  )
}

function FileRow({ tenant, ft, existing, onChange }) {
  const toast = useToast()
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)

  async function upload(file) {
    if (!file) return
    setBusy(true)
    try {
      const updated = await tenantAdminApi.uploadFile(tenant.slug, ft.key, file)
      toast.success(`${ft.label} uploaded and validated.`)
      onChange(updated)
    } catch (err) {
      toast.error(`${ft.label}: ${normalizeError(err).message}`)
    } finally {
      setBusy(false)
    }
  }

  const present = !!existing

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]) }}
      className="flex items-center gap-3 rounded-xl border p-3 transition"
      style={{
        borderColor: drag ? 'var(--brand-500)' : 'var(--line)',
        background: drag ? 'rgba(99,102,241,0.06)' : 'var(--surface)',
        borderStyle: drag ? 'dashed' : 'solid',
      }}
    >
      <span className="text-lg">{present ? '✅' : ft.required ? '⬜' : '➖'}</span>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: 'var(--ink)' }}>
          {ft.label}
          {ft.required && <span className="text-[10px] font-bold uppercase text-brand-500">required</span>}
        </div>
        <div className="truncate text-xs" style={{ color: 'var(--faint)' }}>
          {present ? `${existing.original_name} · ${existing.validation_detail}` : ft.hint}
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept=".json,application/json"
        className="hidden"
        onChange={(e) => upload(e.target.files[0])}
      />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={busy}
        className="rounded-lg border px-3 py-1.5 text-xs font-semibold transition hover:bg-black/5 dark:hover:bg-white/5"
        style={{ borderColor: 'var(--line)', color: 'var(--ink)' }}
      >
        {busy ? <Spinner /> : present ? 'Replace' : 'Upload'}
      </button>
    </div>
  )
}
