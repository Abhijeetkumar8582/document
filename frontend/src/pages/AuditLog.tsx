import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { api, fmt, type AuditPage } from '../api'
import { Empty, Notice, PageHeader, Skeleton } from '../components/ui'

const PAGE_SIZE = 50
const ACTIONS = ['upload', 'view', 'edit', 'status_change', 'download', 'export', 'delete'] as const
const ACTION_LABEL: Record<string, string> = {
  upload: 'Uploaded',
  view: 'Viewed',
  edit: 'Edited',
  status_change: 'Status changed',
  download: 'Downloaded original',
  export: 'Exported report',
  delete: 'Deleted',
}
const ACTION_TONE: Record<string, string> = {
  upload: 'bg-oxford-soft text-oxford',
  view: 'bg-paper text-slate-600',
  edit: 'bg-gilt-soft text-[#7A5F1E]',
  status_change: 'bg-gilt-soft text-[#7A5F1E]',
  download: 'bg-moss-soft text-moss',
  export: 'bg-moss-soft text-moss',
  delete: 'bg-seal-soft text-seal',
}

export default function AuditLog() {
  const [params, setParams] = useSearchParams()
  const action = params.get('action') ?? ''
  const recordId = params.get('record') ?? ''
  const page = Math.max(1, Number(params.get('page') ?? 1))
  const [data, setData] = useState<AuditPage | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .audit({ action, record_id: recordId, page, page_size: PAGE_SIZE })
      .then(setData)
      .catch((e) => setError(e.message))
  }, [action, recordId, page])

  const set = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) (v ? next.set(k, v) : next.delete(k))
    if (!('page' in patch)) next.delete('page')
    setParams(next)
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader eyebrow="FERPA access log" title="Audit log" />

      <div className="settle settle-2 mb-4 flex flex-wrap items-center gap-2">
        <select value={action} onChange={(e) => set({ action: e.target.value || undefined })} className="input w-auto py-1.5" aria-label="Filter by action">
          <option value="">All actions</option>
          {ACTIONS.map((a) => (
            <option key={a} value={a}>
              {ACTION_LABEL[a]}
            </option>
          ))}
        </select>
        {recordId && (
          <div className="flex items-center gap-2 text-sm text-slate-600">
            Record <Link to={`/records/${recordId}`} className="font-mono text-oxford hover:underline">#{recordId}</Link>
            <button onClick={() => set({ record: undefined })} className="text-oxford hover:underline">
              Clear
            </button>
          </div>
        )}
        {data && (
          <div className="ml-auto font-mono text-xs text-slate-500">
            {data.total} {data.total === 1 ? 'event' : 'events'}
          </div>
        )}
      </div>

      {error && <Notice kind="error">{error}</Notice>}
      {!data && !error && <Skeleton />}
      {data && data.items.length === 0 && <Empty title="No events yet">Every upload, view, edit, download, export and deletion will appear here with who did it and when.</Empty>}

      {data && data.items.length > 0 && (
        <div className="card settle settle-3 overflow-x-auto">
          <table className="w-full min-w-[820px] text-sm">
            <thead className="border-b border-line bg-paper">
              <tr>
                <th className="th">When</th>
                <th className="th">Action</th>
                <th className="th">Record</th>
                <th className="th">Detail</th>
                <th className="th">Actor</th>
                <th className="th">From</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.items.map((e) => (
                <tr key={e.id} className="hover:bg-paper">
                  <td className="td whitespace-nowrap font-mono text-xs text-slate-600">{fmt.dateTime(e.created_at)}</td>
                  <td className="td">
                    <span className={`rounded px-2 py-0.5 font-mono text-[11px] tracking-wide ${ACTION_TONE[e.action] ?? 'bg-paper text-slate-600'}`}>
                      {ACTION_LABEL[e.action] ?? e.action}
                    </span>
                  </td>
                  <td className="td font-mono text-xs">
                    {e.record_id !== null ? (
                      e.action === 'delete' ? (
                        <span className="text-slate-400">#{e.record_id}</span>
                      ) : (
                        <Link to={`/records/${e.record_id}`} className="text-oxford hover:underline">
                          #{e.record_id}
                        </Link>
                      )
                    ) : (
                      '—'
                    )}
                  </td>
                  <td className="td max-w-[380px] truncate text-slate-700" title={e.detail}>
                    {e.detail || '—'}
                  </td>
                  <td className="td font-mono text-xs text-slate-600">{e.actor}</td>
                  <td className="td font-mono text-xs text-slate-500">{e.client_ip ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && pages > 1 && (
        <div className="mt-4 flex items-center justify-end gap-2 text-sm">
          <span className="font-mono text-xs text-slate-500">
            Page {page} of {pages}
          </span>
          <button className="btn-ghost px-2" disabled={page <= 1} onClick={() => set({ page: String(page - 1) })} aria-label="Previous page">
            <ChevronLeft size={15} />
          </button>
          <button className="btn-ghost px-2" disabled={page >= pages} onClick={() => set({ page: String(page + 1) })} aria-label="Next page">
            <ChevronRight size={15} />
          </button>
        </div>
      )}
    </div>
  )
}
