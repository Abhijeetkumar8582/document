import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ChevronDown, ChevronUp, ChevronLeft, ChevronRight, Download, UploadCloud, Trash2, Loader2, X } from 'lucide-react'
import { api, fmt, ENGINE_LABEL, type Engine, type RecordPage, type ReviewStatus } from '../api'
import { Confidence, Empty, EngineTag, Notice, PageHeader, Skeleton, Stamp } from '../components/ui'

const PAGE_SIZE = 10
const SORTS = ['created_at', 'student_name', 'institution', 'percentage', 'gpa', 'confidence', 'academic_year'] as const
type SortKey = (typeof SORTS)[number]
const ENGINES: Engine[] = ['text', 'google_docai', 'llm_vision', 'ocr']

export default function Records() {
  const [params, setParams] = useSearchParams()
  const q = params.get('q') ?? ''
  const status = (params.get('status') ?? '') as '' | ReviewStatus
  const engine = (ENGINES.includes(params.get('engine') as Engine) ? params.get('engine') : '') as '' | Engine
  const sort = (SORTS.includes(params.get('sort') as SortKey) ? params.get('sort') : 'created_at') as SortKey
  const order = params.get('order') === 'asc' ? 'asc' : 'desc'
  const page = Math.max(1, Number(params.get('page') ?? 1))

  const [data, setData] = useState<RecordPage | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const headerBox = useRef<HTMLInputElement>(null)

  useEffect(() => {
    let live = true
    setLoading(true)
    api
      .list({ q, status, engine, sort, order, page, page_size: PAGE_SIZE })
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message))
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [q, status, engine, sort, order, page, reload])

  const pageIds = useMemo(() => (data ? data.items.map((r) => r.id) : []), [data])
  const allOnPage = pageIds.length > 0 && pageIds.every((id) => selected.has(id))
  const someOnPage = pageIds.some((id) => selected.has(id))
  useEffect(() => {
    if (headerBox.current) headerBox.current.indeterminate = someOnPage && !allOnPage
  }, [someOnPage, allOnPage])

  const toggleAll = () =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (allOnPage) pageIds.forEach((id) => next.delete(id))
      else pageIds.forEach((id) => next.add(id))
      return next
    })
  const toggleOne = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const deleteSelected = async () => {
    const ids = Array.from(selected)
    setDeleting(true)
    setError(null)
    try {
      const res = await api.removeMany(ids)
      setNotice(`Deleted ${res.deleted} ${res.deleted === 1 ? 'record' : 'records'} and their files.`)
      setSelected(new Set())
      setConfirming(false)
      setReload((n) => n + 1)
      window.setTimeout(() => setNotice(null), 4000)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setDeleting(false)
    }
  }

  const set = (patch: Record<string, string | undefined>) => {
    const next = new URLSearchParams(params)
    for (const [k, v] of Object.entries(patch)) (v ? next.set(k, v) : next.delete(k))
    if (!('page' in patch)) next.delete('page')
    setParams(next)
  }

  const toggleSort = (key: SortKey) => {
    if (sort === key) set({ order: order === 'asc' ? 'desc' : 'asc' })
    else set({ sort: key, order: key === 'student_name' || key === 'institution' ? 'asc' : 'desc' })
  }

  const pages = useMemo(() => (data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1), [data])

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        eyebrow="Register"
        title="Records"
        action={
          <div className="flex gap-2">
            <a href={api.exportUrl()} className="btn-ghost">
              <Download size={16} /> Export CSV
            </a>
            <Link to="/upload" className="btn-primary">
              <UploadCloud size={16} /> Upload
            </Link>
          </div>
        }
      />

      <div className="settle settle-2 mb-4 flex flex-wrap items-center gap-2">
        <div className="flex overflow-hidden rounded-md border border-line bg-paper-2">
          {(
            [
              ['', 'All'],
              ['verified', 'Verified'],
              ['needs_review', 'Needs review'],
            ] as const
          ).map(([value, label]) => (
            <button
              key={value}
              onClick={() => set({ status: value || undefined })}
              className={`px-3 py-1.5 text-sm transition-colors ${status === value ? 'bg-ink text-white' : 'text-slate-600 hover:bg-paper'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <select
          value={engine}
          onChange={(e) => set({ engine: e.target.value || undefined })}
          className="input w-auto py-1.5"
          aria-label="Filter by engine"
        >
          <option value="">Read by: any engine</option>
          {ENGINES.map((e) => (
            <option key={e} value={e}>
              Read by: {ENGINE_LABEL[e]}
            </option>
          ))}
        </select>
        {q && (
          <div className="flex items-center gap-2 text-sm text-slate-600">
            Showing results for <span className="font-mono text-ink">“{q}”</span>
            <button onClick={() => set({ q: undefined })} className="text-oxford hover:underline">
              Clear
            </button>
          </div>
        )}
        {data && (
          <div className="ml-auto font-mono text-xs text-slate-500">
            {data.total} {data.total === 1 ? 'record' : 'records'}
          </div>
        )}
      </div>

      {selected.size > 0 && (
        <div className="settle mb-3 flex flex-wrap items-center gap-3 rounded-md border border-ink/15 bg-ink px-4 py-2 text-sm text-white">
          <span className="font-medium">
            {selected.size} {selected.size === 1 ? 'record' : 'records'} selected
          </span>
          {confirming ? (
            <>
              <span className="text-white/75">Delete {selected.size === 1 ? 'this record' : `these ${selected.size} records`} and their stored files? This is logged and cannot be undone.</span>
              <button className="btn bg-seal text-white hover:bg-seal/90" onClick={deleteSelected} disabled={deleting}>
                {deleting ? <Loader2 size={14} className="animate-spin" /> : <Trash2 size={14} />} {deleting ? 'Deleting…' : 'Yes, delete'}
              </button>
              <button className="btn border border-white/25 text-white hover:bg-white/10" onClick={() => setConfirming(false)} disabled={deleting}>
                Keep
              </button>
            </>
          ) : (
            <>
              <button className="btn border border-white/25 text-white hover:bg-white/10" onClick={() => setConfirming(true)}>
                <Trash2 size={14} /> Delete selected
              </button>
              <button className="ml-auto inline-flex items-center gap-1 text-white/70 hover:text-white" onClick={() => setSelected(new Set())}>
                <X size={14} /> Clear selection
              </button>
            </>
          )}
        </div>
      )}

      {notice && (
        <div className="mb-3">
          <Notice kind="success">{notice}</Notice>
        </div>
      )}
      {error && <Notice kind="error">{error}</Notice>}
      {loading && !data && <Skeleton />}

      {data && data.items.length === 0 && (
        <Empty title={q || status || engine ? 'No records match' : 'No records yet'}>
          {q || status || engine ? 'Try a different name, ID or school, or clear the filters.' : 'Upload a transcript or marksheet to create the first one.'}
        </Empty>
      )}

      {data && data.items.length > 0 && (
        <div className={`card settle settle-3 overflow-x-auto ${loading ? 'opacity-60' : ''}`}>
          <table className="w-full min-w-[1000px] text-sm">
            <thead className="border-b border-line bg-paper">
              <tr>
                <th className="th w-10 pr-0">
                  <input
                    ref={headerBox}
                    type="checkbox"
                    className="checkbox"
                    checked={allOnPage}
                    onChange={toggleAll}
                    aria-label={allOnPage ? 'Deselect all records on this page' : 'Select all records on this page'}
                  />
                </th>
                <Th label="Student" k="student_name" sort={sort} order={order} onClick={toggleSort} />
                <Th label="Institution" k="institution" sort={sort} order={order} onClick={toggleSort} />
                <th className="th">Program</th>
                <Th label="Year" k="academic_year" sort={sort} order={order} onClick={toggleSort} />
                <th className="th text-right">Courses</th>
                <Th label="GPA" k="gpa" sort={sort} order={order} onClick={toggleSort} align="right" />
                <Th label="Score" k="percentage" sort={sort} order={order} onClick={toggleSort} align="right" />
                <th className="th">Read by</th>
                <Th label="Fields" k="confidence" sort={sort} order={order} onClick={toggleSort} />
                <th className="th">Status</th>
                <Th label="Added" k="created_at" sort={sort} order={order} onClick={toggleSort} />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {data.items.map((r) => (
                <tr key={r.id} className={`group hover:bg-paper ${selected.has(r.id) ? 'bg-oxford-soft/60' : ''}`}>
                  <td className="td w-10 pr-0">
                    <input
                      type="checkbox"
                      className="checkbox"
                      checked={selected.has(r.id)}
                      onChange={() => toggleOne(r.id)}
                      aria-label={`Select ${r.student_name ?? r.file_name}`}
                    />
                  </td>
                  <td className="td">
                    <Link to={`/records/${r.id}`} className="font-medium text-ink group-hover:underline">
                      {r.student_name ?? <span className="italic text-slate-400">Unnamed</span>}
                    </Link>
                    <div className="font-mono text-xs text-slate-500">{r.roll_number ?? r.file_name}</div>
                  </td>
                  <td className="td max-w-[220px] truncate text-slate-700">{r.institution ?? '—'}</td>
                  <td className="td max-w-[200px] truncate text-slate-700">
                    {r.program ?? '—'}
                    {r.term && <div className="text-xs text-slate-500">{r.term}</div>}
                  </td>
                  <td className="td whitespace-nowrap font-mono text-slate-700">{r.academic_year ?? '—'}</td>
                  <td className="td text-right font-mono">{r.subject_count}</td>
                  <td className="td whitespace-nowrap text-right font-mono">
                    {fmt.gpa(r.gpa)}
                    {r.credits_earned !== null && <div className="text-xs text-slate-500">{fmt.num(r.credits_earned, 1)} cr</div>}
                  </td>
                  <td className="td whitespace-nowrap text-right font-mono">{fmt.pct(r.percentage)}</td>
                  <td className="td">
                    <EngineTag engine={r.extraction_method} confidence={r.engine_confidence} compact />
                  </td>
                  <td className="td">
                    <Confidence value={r.confidence} />
                  </td>
                  <td className="td">
                    <Stamp status={r.review_status} />
                  </td>
                  <td className="td whitespace-nowrap font-mono text-xs text-slate-500">{fmt.date(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > 0 && (
        <nav className="mt-4 flex flex-wrap items-center gap-3 text-sm" aria-label="Pagination">
          <span className="font-mono text-xs text-slate-500">
            Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, data.total)} of {data.total}
          </span>
          <div className="ml-auto flex items-center gap-1">
            <button className="btn-ghost px-2" disabled={page <= 1} onClick={() => set({ page: String(page - 1) })} aria-label="Previous page">
              <ChevronLeft size={15} />
            </button>
            {pageNumbers(page, pages).map((p, i) =>
              p === '…' ? (
                <span key={`gap-${i}`} className="px-1 font-mono text-xs text-slate-400">
                  …
                </span>
              ) : (
                <button
                  key={p}
                  onClick={() => set({ page: String(p) })}
                  aria-current={p === page ? 'page' : undefined}
                  className={`min-w-[32px] rounded-md px-2 py-1.5 font-mono text-xs transition-colors ${
                    p === page ? 'bg-ink text-white' : 'border border-line bg-paper-2 text-slate-700 hover:border-line-2 hover:bg-paper'
                  }`}
                >
                  {p}
                </button>
              ),
            )}
            <button className="btn-ghost px-2" disabled={page >= pages} onClick={() => set({ page: String(page + 1) })} aria-label="Next page">
              <ChevronRight size={15} />
            </button>
          </div>
        </nav>
      )}
    </div>
  )
}

/** 1 … 4 5 [6] 7 8 … 20: always the first, last, and a window around the current page. */
function pageNumbers(current: number, total: number): (number | '…')[] {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const out: (number | '…')[] = [1]
  const lo = Math.max(2, current - 1)
  const hi = Math.min(total - 1, current + 1)
  if (lo > 2) out.push('…')
  for (let p = lo; p <= hi; p++) out.push(p)
  if (hi < total - 1) out.push('…')
  out.push(total)
  return out
}

function Th({
  label,
  k,
  sort,
  order,
  onClick,
  align,
}: {
  label: string
  k: SortKey
  sort: SortKey
  order: 'asc' | 'desc'
  onClick: (k: SortKey) => void
  align?: 'right'
}) {
  const active = sort === k
  return (
    <th className={`th ${align === 'right' ? 'text-right' : ''}`}>
      <button onClick={() => onClick(k)} className={`inline-flex items-center gap-1 uppercase tracking-[0.14em] hover:text-ink ${active ? 'text-ink' : ''}`}>
        {label}
        {active && (order === 'asc' ? <ChevronUp size={12} /> : <ChevronDown size={12} />)}
      </button>
    </th>
  )
}
