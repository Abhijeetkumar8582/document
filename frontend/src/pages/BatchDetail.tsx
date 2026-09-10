import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, RotateCcw, XCircle, ArrowRight } from 'lucide-react'
import { api, fmt, ENGINE_LABEL, type Batch, type Job, type JobStatus } from '../api'
import { Notice, Skeleton } from '../components/ui'
import { BatchBar, BatchStatusChip, JobStatusChip } from '../components/batch'

const POLL_MS = 2000
const FILTERS: { value: '' | JobStatus; label: string }[] = [
  { value: '', label: 'All' },
  { value: 'processing', label: 'Processing' },
  { value: 'queued', label: 'Waiting' },
  { value: 'done', label: 'Filed' },
  { value: 'dead', label: 'Needs attention' },
  { value: 'skipped', label: 'Duplicates' },
]

export default function BatchDetail() {
  const { id } = useParams()
  const batchId = Number(id)
  const [batch, setBatch] = useState<Batch | null>(null)
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [filter, setFilter] = useState<'' | JobStatus>('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    Promise.all([api.batch(batchId), api.batchJobs(batchId, { status: filter, page_size: 500 })])
      .then(([b, j]) => {
        setBatch(b)
        setJobs(j.items)
      })
      .catch((e) => setError(e.message))
  }, [batchId, filter])

  useEffect(load, [load])
  useEffect(() => {
    if (!batch || (batch.status !== 'running' && batch.status !== 'queued')) return
    const t = setInterval(load, POLL_MS)
    return () => clearInterval(t)
  }, [batch, load])

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
      load()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (error && !batch) return <Notice kind="error">{error}</Notice>
  if (!batch) return <Skeleton />

  const c = batch.counts
  const live = batch.status === 'running' || batch.status === 'queued'
  const elapsed = batch.started_at ? ((batch.finished_at ? new Date(batch.finished_at + 'Z') : new Date()).getTime() - new Date(batch.started_at + 'Z').getTime()) / 1000 : null

  return (
    <div className="mx-auto max-w-6xl">
      <Link to="/upload" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-ink">
        <ArrowLeft size={14} /> Upload
      </Link>

      <div className="settle card">
        <div className="flex flex-wrap items-start justify-between gap-4 px-6 py-5">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <span className="eyebrow">Batch #{batch.id}</span>
              <BatchStatusChip status={batch.status} />
              <span className="font-mono text-[11px] text-slate-500">scans via {ENGINE_LABEL[batch.mode as keyof typeof ENGINE_LABEL] ?? 'auto'}</span>
            </div>
            <h1 className="mt-1 font-display text-[26px] font-semibold leading-tight tracking-tight text-ink">{batch.name}</h1>
            <div className="mt-1 text-sm text-slate-600">
              {batch.total_jobs} files · {fmt.bytes(batch.total_bytes)} · by <span className="font-mono">{batch.actor}</span> · {fmt.dateTime(batch.created_at)}
              {elapsed !== null && <span className="font-mono text-xs text-slate-500"> · {elapsed < 90 ? `${Math.round(elapsed)}s` : `${Math.round(elapsed / 60)} min`}{live ? ' so far' : ''}</span>}
            </div>
          </div>
          <div className="flex gap-2">
            {c.dead > 0 && (
              <button className="btn-primary" disabled={busy} onClick={() => act(() => api.retryBatch(batch.id))}>
                <RotateCcw size={15} /> Retry {c.dead} failed
              </button>
            )}
            {live && (c.queued > 0 || c.failed > 0) && (
              <button className="btn-danger" disabled={busy} onClick={() => act(() => api.cancelBatch(batch.id))}>
                <XCircle size={15} /> Cancel waiting files
              </button>
            )}
          </div>
        </div>

        <div className="border-t border-line px-6 py-4">
          <BatchBar batch={batch} />
          <div className="mt-3 grid grid-cols-3 gap-3 sm:grid-cols-6">
            <Count n={c.done} label="Filed" tone="text-moss" />
            <Count n={c.skipped} label="Duplicates" tone="text-moss/70" />
            <Count n={c.processing} label="Processing" tone="text-oxford" />
            <Count n={c.queued + c.failed} label="Waiting" tone="text-slate-600" sub={c.failed ? `${c.failed} retrying` : undefined} />
            <Count n={c.dead} label="Need attention" tone="text-seal" />
            <Count n={c.cancelled} label="Cancelled" tone="text-slate-400" />
          </div>
        </div>
      </div>

      {error && (
        <div className="mt-4">
          <Notice kind="error">{error}</Notice>
        </div>
      )}

      <div className="settle settle-2 mt-6 flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded-md border border-line bg-paper-2">
          {FILTERS.map((f) => (
            <button key={f.value} onClick={() => setFilter(f.value)} className={`px-3 py-1.5 text-sm transition-colors ${filter === f.value ? 'bg-ink text-white' : 'text-slate-600 hover:bg-paper'}`}>
              {f.label}
            </button>
          ))}
        </div>
        {jobs && (
          <span className="ml-auto font-mono text-xs text-slate-500">
            {jobs.length} {jobs.length === 1 ? 'file' : 'files'}
          </span>
        )}
      </div>

      {jobs && (
        <div className="settle settle-3 card mt-3 overflow-x-auto">
          <table className="w-full min-w-[900px] text-sm">
            <thead className="border-b border-line bg-paper">
              <tr>
                <th className="th">File</th>
                <th className="th">Status</th>
                <th className="th w-56">Stage</th>
                <th className="th text-right">Tries</th>
                <th className="th">Outcome</th>
                <th className="th w-10" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {jobs.length === 0 && (
                <tr>
                  <td className="td py-8 text-center text-slate-500" colSpan={6}>
                    Nothing in this state.
                  </td>
                </tr>
              )}
              {jobs.map((j) => {
                const pct = j.progress_total > 0 ? Math.round((j.progress_done / j.progress_total) * 100) : null
                return (
                  <tr key={j.id} className="hover:bg-paper">
                    <td className="td">
                      <div className="font-medium text-ink">{j.file_name}</div>
                      <div className="font-mono text-xs text-slate-500">
                        #{j.id} · {fmt.bytes(j.file_size)}
                      </div>
                    </td>
                    <td className="td">
                      <JobStatusChip status={j.status} />
                    </td>
                    <td className="td">
                      {j.status === 'processing' ? (
                        <div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-line">
                            <div className={`h-full bg-oxford transition-all ${pct === null ? 'w-1/3 animate-pulse' : ''}`} style={pct !== null ? { width: `${pct}%` } : undefined} />
                          </div>
                          <div className="mt-1 font-mono text-[11px] text-slate-500">
                            {j.stage}
                            {j.progress_total > 1 && ` · ${j.progress_done}/${j.progress_total} pages`}
                          </div>
                        </div>
                      ) : (
                        <span className="font-mono text-xs text-slate-500">{j.stage || '—'}</span>
                      )}
                    </td>
                    <td className="td text-right font-mono text-slate-600">
                      {j.attempts}/{j.max_attempts}
                    </td>
                    <td className="td max-w-[360px]">
                      {j.status === 'done' && j.record_id && (
                        <Link to={`/records/${j.record_id}`} className="inline-flex items-center gap-1 text-oxford hover:underline">
                          Record #{j.record_id} <ArrowRight size={13} />
                        </Link>
                      )}
                      {j.status === 'skipped' && (
                        <span className="text-slate-600">
                          {j.duplicate_of ? (
                            <>
                              Same file as{' '}
                              <Link to={`/records/${j.duplicate_of}`} className="text-oxford hover:underline">
                                record #{j.duplicate_of}
                              </Link>
                            </>
                          ) : (
                            j.error
                          )}
                        </span>
                      )}
                      {(j.status === 'dead' || j.status === 'failed') && <span className="block truncate text-seal" title={j.error ?? ''}>{j.error}</span>}
                      {j.status === 'failed' && j.next_attempt_at && <span className="font-mono text-[11px] text-slate-500">next try {fmt.dateTime(j.next_attempt_at)}</span>}
                    </td>
                    <td className="td">
                      {(j.status === 'dead' || j.status === 'cancelled') && (
                        <button className="rounded p-1 text-slate-400 hover:bg-oxford-soft hover:text-oxford" title="Retry this file" disabled={busy} onClick={() => act(() => api.retryJob(j.id))}>
                          <RotateCcw size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function Count({ n, label, tone, sub }: { n: number; label: string; tone: string; sub?: string }) {
  return (
    <div>
      <div className={`font-display text-2xl font-semibold leading-none ${n ? tone : 'text-slate-300'}`}>{n}</div>
      <div className="mt-1 eyebrow">{label}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  )
}
