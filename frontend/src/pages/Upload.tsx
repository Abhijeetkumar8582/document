import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Link } from 'react-router-dom'
import { FileText, UploadCloud, X, ArrowRight, Cloud, Sparkles, ScanLine, Wand2, Play, Loader2, Check, AlertCircle, Eye, FolderUp, Archive } from 'lucide-react'
import { api, fmt, type Batch, type EngineStatus, type Mode } from '../api'
import { Notice, PageHeader, Stamp } from '../components/ui'
import { BatchBar, BatchStatusChip } from '../components/batch'
import { analysis, isTerminal, type Session } from '../lib/analysis'

const ACCEPT = '.pdf,.png,.jpg,.jpeg,.webp,.tif,.tiff,.bmp,.docx,.txt,.csv,.zip'

type Staged = { id: string; file: File; path: string }

export default function Upload() {
  const [staged, setStaged] = useState<Staged[]>([])
  const [dragging, setDragging] = useState(false)
  const [mode, setMode] = useState<Mode>('auto')
  const [engines, setEngines] = useState<EngineStatus | null>(null)
  const [starting, setStarting] = useState(false)
  const [batches, setBatches] = useState<Batch[] | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const folderRef = useRef<HTMLInputElement>(null)
  const sessions = useSyncExternalStore(analysis.subscribe, analysis.getSessions)
  const activeCount = sessions.filter((s) => s.phase === 'uploading' || s.phase === 'queuing' || s.phase === 'processing').length

  useEffect(() => {
    api.engines().then(setEngines).catch(() => setEngines(null))
  }, [])

  // Batch history, refreshed while anything is still running.
  useEffect(() => {
    const load = () => api.batches({ page_size: 8 }).then((b) => setBatches(b.items)).catch(() => null)
    load()
    if (!activeCount) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [activeCount])

  const add = useCallback((files: FileList | File[]) => {
    const fresh: Staged[] = Array.from(files).map((file) => ({
      id: `${file.name}-${file.size}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      file,
      path: (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
    }))
    setStaged((prev) => [...prev, ...fresh])
  }, [])

  const start = async () => {
    if (!staged.length) return
    setStarting(true)
    const files = staged.map((s) => s.file)
    setStaged([])
    try {
      await analysis.start(files, mode)
    } finally {
      setStarting(false)
    }
  }

  const modes: { value: Mode; label: string; hint: string; icon: typeof Wand2; ready: boolean }[] = [
    { value: 'auto', label: 'Auto', hint: 'Text layer first. Scans go to Document AI, then Local LLM Cloud.', icon: Wand2, ready: true },
    { value: 'text', label: 'Text layer', hint: 'Only read embedded text. Fast and exact for digital PDFs.', icon: FileText, ready: true },
    {
      value: 'google_docai',
      label: 'Google Document AI',
      hint: engines ? `Cloud OCR. Kept above ${Math.round((engines.google_docai.threshold ?? 0.7) * 100)}% confidence.` : 'Cloud OCR.',
      icon: Cloud,
      ready: engines?.google_docai.ready ?? false,
    },
    {
      value: 'llm_vision',
      label: 'Local LLM Cloud',
      hint: engines ? `${engines.llm_vision.model}, one call per page.` : 'One call per page.',
      icon: Sparkles,
      ready: engines?.llm_vision.ready ?? false,
    },
    { value: 'ocr', label: 'Local OCR', hint: 'Tesseract on this server.', icon: ScanLine, ready: engines?.ocr.ready ?? false },
  ]

  const totalBytes = staged.reduce((n, s) => n + s.file.size, 0)
  const zipCount = staged.filter((s) => s.file.name.toLowerCase().endsWith('.zip')).length

  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader eyebrow="Intake" title="Upload records" />

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          if (e.dataTransfer.files.length) add(e.dataTransfer.files)
        }}
        className={`settle settle-2 relative rounded-lg border-2 border-dashed px-6 py-10 text-center transition-colors ${
          dragging ? 'border-oxford bg-oxford-soft' : 'border-line-2 bg-paper-2'
        }`}
      >
        <Tray />
        <div className="mt-4 font-display text-lg font-semibold text-ink">Drop transcripts, marksheets or grade reports here</div>
        <div className="mt-1 text-sm text-slate-500">
          One file or a thousand. Digital PDFs, Word, plain text, scans and photos, whole folders, or a ZIP. Up to 25 MB per file.
        </div>
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          <button className="btn-primary" onClick={() => inputRef.current?.click()}>
            <UploadCloud size={16} /> Choose files
          </button>
          <button className="btn-ghost" onClick={() => folderRef.current?.click()}>
            <FolderUp size={16} /> Choose a folder
          </button>
          <span className="inline-flex items-center gap-1 text-xs text-slate-500">
            <Archive size={13} /> ZIP archives are unpacked for you
          </span>
        </div>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={ACCEPT}
          className="sr-only"
          onChange={(e) => {
            if (e.target.files?.length) add(e.target.files)
            e.target.value = ''
          }}
        />
        <input
          ref={folderRef}
          type="file"
          multiple
          className="sr-only"
          // Non-standard but supported by every current browser.
          {...({ webkitdirectory: '', directory: '' } as Record<string, string>)}
          onChange={(e) => {
            if (e.target.files?.length) add(e.target.files)
            e.target.value = ''
          }}
        />
      </div>

      {staged.length > 0 && (
        <section className="settle card mt-4 overflow-hidden">
          <div className="flex flex-wrap items-center gap-3 border-b border-line bg-paper px-4 py-3">
            <div className="eyebrow">Ready to analyze</div>
            <span className="font-mono text-xs text-slate-500">
              {staged.length} {staged.length === 1 ? 'file' : 'files'} · {fmt.bytes(totalBytes)}
              {zipCount > 0 && ` · ${zipCount} ZIP`}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <button className="btn-ghost" onClick={() => setStaged([])} disabled={starting}>
                Clear
              </button>
              <button className="btn-primary" onClick={start} disabled={starting}>
                {starting ? <Loader2 size={15} className="animate-spin" /> : <Play size={15} />} Start analysis
              </button>
            </div>
          </div>
          <ul className="max-h-64 divide-y divide-line overflow-y-auto">
            {staged.map((s) => (
              <li key={s.id} className="flex items-center gap-3 px-4 py-2.5">
                {s.file.name.toLowerCase().endsWith('.zip') ? <Archive size={16} strokeWidth={1.75} className="shrink-0 text-slate-500" /> : <FileText size={16} strokeWidth={1.75} className="shrink-0 text-slate-500" />}
                <span className="min-w-0 flex-1 truncate text-sm text-ink">{s.path}</span>
                <span className="font-mono text-xs text-slate-500">{fmt.bytes(s.file.size)}</span>
                <button
                  className="rounded p-1 text-slate-400 hover:bg-paper hover:text-slate-700"
                  aria-label={`Remove ${s.file.name}`}
                  onClick={() => setStaged((prev) => prev.filter((p) => p.id !== s.id))}
                >
                  <X size={14} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="settle settle-3 mt-5">
        <div className="eyebrow mb-2">How to read scans</div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5" role="radiogroup" aria-label="Processing engine">
          {modes.map(({ value, label, hint, icon: Icon, ready }) => {
            const active = mode === value
            return (
              <button
                key={value}
                role="radio"
                aria-checked={active}
                disabled={!ready}
                onClick={() => setMode(value)}
                title={ready ? hint : `${label} is not configured on this server.`}
                className={`flex flex-col items-start gap-1 rounded-md border px-3 py-2.5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-45 ${
                  active ? 'border-ink bg-ink text-white' : 'border-line bg-paper-2 hover:border-line-2'
                }`}
              >
                <span className="flex items-center gap-1.5 text-[13px] font-medium">
                  <Icon size={14} /> {label}
                </span>
                <span className={`text-[11.5px] leading-4 ${active ? 'text-white/70' : 'text-slate-500'}`}>{ready ? hint : 'Not configured'}</span>
              </button>
            )
          })}
        </div>
        {engines && !engines.google_docai.ready && !engines.llm_vision.ready && !engines.ocr.ready && (
          <div className="mt-3">
            <Notice kind="info">
              No scan engine is set up yet, so only files with a text layer can be read. Add Google Document AI or a Gemini key in the server's .env to handle scans and photos.
            </Notice>
          </div>
        )}
      </section>

      <div className="settle settle-3 mt-4 text-xs leading-5 text-slate-500">
        Analysis runs on the server. Close the progress window or leave this page and it keeps going; every file ends up filed or listed with a reason.
        <br />
        These are education records under FERPA. Social Security numbers and dates of birth are removed before anything is stored, and every upload is written to the audit log.
      </div>

      {sessions.length > 0 && (
        <section className="settle mt-8">
          <div className="eyebrow mb-3">This session</div>
          <div className="space-y-3">
            {sessions.map((s) => (
              <SessionCard key={s.id} s={s} />
            ))}
          </div>
        </section>
      )}

      {batches && batches.length > 0 && (
        <section className="settle mt-8">
          <div className="eyebrow mb-3">Recent uploads</div>
          <div className="card overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="border-b border-line bg-paper">
                <tr>
                  <th className="th">Upload</th>
                  <th className="th w-56">Progress</th>
                  <th className="th">Status</th>
                  <th className="th text-right">Files</th>
                  <th className="th">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {batches.map((b) => (
                  <tr key={b.id} className="group hover:bg-paper">
                    <td className="td">
                      <Link to={`/batches/${b.id}`} className="font-medium text-ink group-hover:underline">
                        {b.name}
                      </Link>
                      <div className="font-mono text-xs text-slate-500">#{b.id}</div>
                    </td>
                    <td className="td">
                      <BatchBar batch={b} />
                    </td>
                    <td className="td">
                      <BatchStatusChip status={b.status} />
                    </td>
                    <td className="td text-right font-mono">
                      {b.finished_jobs}/{b.total_jobs}
                    </td>
                    <td className="td whitespace-nowrap font-mono text-xs text-slate-500">{fmt.timeAgo(b.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  )
}

function SessionCard({ s }: { s: Session }) {
  const running = s.phase === 'uploading' || s.phase === 'queuing' || s.phase === 'processing'
  const finished = s.files.filter(isTerminal).length
  const filed = s.files.filter((f) => f.job?.status === 'done')
  const failed = s.files.filter((f) => f.uploadError || f.job?.status === 'dead').length
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        {running ? <Loader2 size={16} className="animate-spin text-oxford" /> : failed ? <AlertCircle size={16} className="text-seal" /> : <Check size={16} className="text-moss" />}
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-medium text-ink">{s.name}</div>
          <div className="font-mono text-[11px] text-slate-500">
            {running ? `${finished}/${s.files.length} done` : `${filed.length} filed${failed ? `, ${failed} failed` : ''}`} · started {new Date(s.startedAt).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
            {s.batchId && (
              <>
                {' · '}
                <Link to={`/batches/${s.batchId}`} className="text-oxford hover:underline">
                  details
                </Link>
              </>
            )}
          </div>
        </div>
        <button className="btn-ghost" onClick={() => analysis.openOverlay(s.id)}>
          <Eye size={14} /> {running ? 'Watch progress' : 'Show results'}
        </button>
        {!running && (
          <button className="rounded p-1 text-slate-400 hover:bg-paper hover:text-slate-700" aria-label="Dismiss" onClick={() => analysis.dismiss(s.id)}>
            <X size={15} />
          </button>
        )}
      </div>
      {filed.length > 0 && (
        <ul className="divide-y divide-line border-t border-line">
          {filed.slice(0, 8).map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-sm">
              <span className="font-medium text-ink">{f.record!.student_name ?? 'Name not found'}</span>
              {f.record!.institution && <span className="truncate text-slate-600">· {f.record!.institution}</span>}
              <span className="font-mono text-xs text-slate-500">{f.record!.subject_count} courses · {fmt.score(f.record!)}</span>
              <Stamp status={f.record!.review_status} />
              <Link to={`/records/${f.record!.id}`} className="ml-auto inline-flex items-center gap-1 text-oxford hover:underline">
                Open record <ArrowRight size={13} />
              </Link>
            </li>
          ))}
          {filed.length > 8 && (
            <li className="px-4 py-2 text-xs text-slate-500">
              and {filed.length - 8} more.{' '}
              <Link to="/records" className="text-oxford hover:underline">
                See all records
              </Link>
            </li>
          )}
        </ul>
      )}
    </div>
  )
}

function Tray() {
  return (
    <svg width="96" height="64" viewBox="0 0 96 64" className="mx-auto" aria-hidden="true">
      <rect x="22" y="6" width="44" height="54" rx="2" fill="#fff" stroke="#CBD2DC" />
      <rect x="28" y="2" width="44" height="54" rx="2" fill="#fff" stroke="#CBD2DC" />
      <line x1="36" y1="14" x2="64" y2="14" stroke="#E1E5EB" strokeWidth="2" />
      <line x1="36" y1="22" x2="58" y2="22" stroke="#E1E5EB" strokeWidth="2" />
      <line x1="36" y1="30" x2="62" y2="30" stroke="#E1E5EB" strokeWidth="2" />
      <path d="M8 40 H88 L82 62 H14 Z" fill="#0E1A2B" />
      <path d="M8 40 H88" stroke="#B8923E" strokeWidth="2" />
    </svg>
  )
}
