import { useEffect, useSyncExternalStore } from 'react'
import { Link } from 'react-router-dom'
import { X, ArrowRight, Check, AlertCircle, Loader2, ExternalLink } from 'lucide-react'
import { fmt } from '../api'
import { analysis, isTerminal, type FileTask, type Session } from '../lib/analysis'
import { Stamp } from './ui'

const STAGE_LABEL: Record<string, string> = {
  starting: 'Starting',
  reading: 'Reading file',
  'text layer': 'Reading text layer',
  'google document ai': 'Google Document AI',
  'rendering pages': 'Rendering pages',
  'gemini vision': 'Local LLM Cloud',
  'local ocr': 'Local OCR',
  parsing: 'Extracting fields',
  filed: 'Filed',
  duplicate: 'Already on file',
  'gave up': 'Could not read',
  rejected: 'Could not read',
}

function stageOf(f: FileTask): string {
  if (f.uploadError) return 'Upload failed'
  if (!f.job) return f.uploadPct < 100 ? `Uploading ${f.uploadPct}%` : 'Waiting for a worker'
  const j = f.job
  if (j.status === 'queued') return 'Waiting for a worker'
  if (j.status === 'failed') return `Retrying (${j.stage})`
  const base = STAGE_LABEL[j.stage] ?? (j.stage || 'Working')
  if (j.status === 'processing' && j.progress_total > 1) return `${base} · page ${j.progress_done}/${j.progress_total}`
  return base
}

export function AnalysisOverlay() {
  const sessions = useSyncExternalStore(analysis.subscribe, analysis.getSessions)
  const openId = useSyncExternalStore(analysis.subscribe, analysis.getOverlay)
  const session = sessions.find((s) => s.id === openId)

  useEffect(() => {
    if (!session) return
    // Move focus into the dialog, keep Tab inside it, and give it back on close.
    const before = document.activeElement as HTMLElement | null
    const panel = document.getElementById('analysis-dialog')
    const focusables = () => Array.from(panel?.querySelectorAll<HTMLElement>('button, a[href], input, [tabindex]:not([tabindex="-1"])') ?? []).filter((el) => !el.hasAttribute('disabled'))
    focusables()[0]?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') analysis.closeOverlay()
      if (e.key === 'Tab') {
        const els = focusables()
        if (!els.length) return
        const first = els[0]
        const last = els[els.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      before?.focus?.()
    }
  }, [session])

  if (!session) return null
  return <Overlay session={session} />
}

function Overlay({ session }: { session: Session }) {
  const total = session.files.length
  const finished = session.files.filter(isTerminal).length
  const filed = session.files.filter((f) => f.job?.status === 'done').length
  const failed = session.files.filter((f) => f.uploadError || f.job?.status === 'dead').length
  const active = session.files.find((f) => f.job?.status === 'processing') ?? session.files.find((f) => !isTerminal(f))
  const running = session.phase !== 'done' && session.phase !== 'error'
  const pct = total ? Math.round((finished / total) * 100) : 0

  const headline =
    session.phase === 'uploading'
      ? `Uploading ${total} ${total === 1 ? 'document' : 'documents'}`
      : session.phase === 'queuing'
        ? 'Handing off to the workers'
        : session.phase === 'processing'
          ? `Analyzing ${total} ${total === 1 ? 'document' : 'documents'}`
          : session.phase === 'error'
            ? 'Could not start'
            : failed
              ? `Done, ${failed} ${failed === 1 ? 'needs' : 'need'} attention`
              : 'All done'

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/60 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label={headline}>
      <div id="analysis-dialog" className="settle flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg border border-line bg-paper-2 shadow-lift">
        <div className="flex items-start gap-4 border-b border-line px-6 py-4">
          <div className="min-w-0 flex-1">
            <div className="eyebrow">{session.name}</div>
            <h2 className="mt-0.5 font-display text-[22px] font-semibold leading-tight tracking-tight text-ink">{headline}</h2>
            <div className="mt-1 text-sm text-slate-500">
              {running ? 'Runs on the server. Close this window any time; nothing stops.' : session.error ?? `${filed} filed, ${session.files.filter((f) => f.job?.status === 'skipped').length} already on file, ${failed} failed.`}
            </div>
          </div>
          <button onClick={analysis.closeOverlay} className="btn-ghost shrink-0" aria-label="Close and keep running">
            <X size={15} /> {running ? 'Close, keep running' : 'Close'}
          </button>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[240px_1fr]">
          <div className="flex flex-col items-center justify-center gap-4 border-b border-line bg-paper px-6 py-8 md:border-b-0 md:border-r">
            <Scanner running={running} failed={!running && failed > 0} />
            <div className="text-center">
              <div className="font-mono text-[11px] uppercase tracking-[0.14em] text-slate-500">{running ? 'Now' : 'Result'}</div>
              <div className="mt-1 text-sm font-medium text-ink">
                {running && active ? (
                  <>
                    <span className="block truncate max-w-[200px]" title={active.name}>{active.name}</span>
                    <span className="text-slate-600">{stageOf(active)}<Dots /></span>
                  </>
                ) : running ? (
                  <span>Preparing<Dots /></span>
                ) : (
                  <span>{filed} of {total} filed</span>
                )}
              </div>
            </div>
          </div>

          <ul className="min-h-0 overflow-y-auto divide-y divide-line">
            {session.files.map((f) => (
              <FileRow key={f.id} f={f} />
            ))}
            {session.files.length === 0 && <li className="px-5 py-8 text-center text-sm text-slate-500">Loading files…</li>}
          </ul>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-line px-6 py-3">
          <div className="h-1.5 min-w-[140px] flex-1 overflow-hidden rounded-full bg-line">
            <div className={`h-full transition-all ${failed && !running ? 'bg-gilt' : 'bg-moss'}`} style={{ width: `${pct}%` }} />
          </div>
          <span className="font-mono text-xs text-slate-500">
            {finished}/{total} · {pct}%
          </span>
          {session.batchId && (
            <Link to={`/batches/${session.batchId}`} onClick={analysis.closeOverlay} className="inline-flex items-center gap-1 text-sm text-oxford hover:underline">
              Batch #{session.batchId} <ExternalLink size={13} />
            </Link>
          )}
          {!running && (
            <button className="btn-primary" onClick={() => analysis.closeOverlay()}>
              <Check size={15} /> Done
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

function FileRow({ f }: { f: FileTask }) {
  const j = f.job
  const done = j?.status === 'done' && f.record
  const dup = j?.status === 'skipped'
  const dead = f.uploadError || j?.status === 'dead'
  const working = !isTerminal(f)
  return (
    <li className="flex items-start gap-3 px-5 py-3">
      <div className="mt-0.5 w-5 shrink-0">
        {done && <Check size={16} className="text-moss" />}
        {dup && <Check size={16} className="text-moss/60" />}
        {dead && <AlertCircle size={16} className="text-seal" />}
        {working && <Loader2 size={16} className={`text-oxford ${j?.status === 'processing' || !j ? 'animate-spin' : 'opacity-40'}`} />}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="truncate text-sm font-medium text-ink">{f.name}</span>
          <span className="font-mono text-[11px] text-slate-500">{fmt.bytes(f.size)}</span>
          {done && <Stamp status={f.record!.review_status} />}
        </div>
        {working && (
          <div className="mt-1.5">
            {!f.job && f.uploadPct < 100 && (
              <div className="h-1 overflow-hidden rounded-full bg-line">
                <div className="h-full bg-oxford transition-all" style={{ width: `${f.uploadPct}%` }} />
              </div>
            )}
            {j?.status === 'processing' && j.progress_total > 1 && (
              <div className="h-1 overflow-hidden rounded-full bg-line">
                <div className="h-full bg-oxford transition-all" style={{ width: `${(j.progress_done / j.progress_total) * 100}%` }} />
              </div>
            )}
            <div className="mt-1 font-mono text-[11px] text-slate-500">{stageOf(f)}</div>
          </div>
        )}
        {done && (
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-sm text-slate-600">
            <span>{f.record!.student_name ?? 'Name not found'}</span>
            {f.record!.institution && <span className="truncate">· {f.record!.institution}</span>}
            <span className="font-mono text-xs text-slate-500">{f.record!.subject_count} courses · {fmt.score(f.record!)}</span>
            <Link to={`/records/${f.record!.id}`} onClick={analysis.closeOverlay} className="inline-flex items-center gap-1 text-oxford hover:underline">
              Open <ArrowRight size={13} />
            </Link>
          </div>
        )}
        {dup && (
          <div className="mt-1 text-sm text-slate-600">
            Already on file
            {j?.duplicate_of && (
              <>
                {' as '}
                <Link to={`/records/${j.duplicate_of}`} onClick={analysis.closeOverlay} className="text-oxford hover:underline">
                  record #{j.duplicate_of}
                </Link>
              </>
            )}
          </div>
        )}
        {dead && <div className="mt-1 text-sm text-seal">{f.uploadError ?? j?.error}</div>}
      </div>
    </li>
  )
}

function Dots() {
  return <span className="dots" aria-hidden="true" />
}

/** A sheet on the desk with a scanning beam sweeping it while work is in progress. */
function Scanner({ running, failed }: { running: boolean; failed: boolean }) {
  return (
    <div className={`scanner ${running ? 'is-running' : ''} ${failed ? 'is-failed' : 'is-done'}`} aria-hidden="true">
      <svg viewBox="0 0 120 150" width="120" height="150">
        <rect x="6" y="4" width="108" height="142" rx="4" fill="#fff" stroke="#CBD2DC" />
        <rect x="18" y="16" width="52" height="7" rx="1.5" fill="#0E1A2B" className="docline" />
        <rect x="18" y="30" width="84" height="3" rx="1.5" className="docline d1" />
        <rect x="18" y="38" width="70" height="3" rx="1.5" className="docline d2" />
        <rect x="18" y="46" width="78" height="3" rx="1.5" className="docline d3" />
        <line x1="18" y1="58" x2="102" y2="58" stroke="#E1E5EB" />
        <rect x="18" y="64" width="34" height="3" rx="1.5" className="docline d1" />
        <rect x="68" y="64" width="18" height="3" rx="1.5" className="docline d2" />
        <rect x="94" y="64" width="8" height="3" rx="1.5" className="docline d3" />
        <rect x="18" y="72" width="40" height="3" rx="1.5" className="docline d2" />
        <rect x="68" y="72" width="18" height="3" rx="1.5" className="docline d3" />
        <rect x="94" y="72" width="8" height="3" rx="1.5" className="docline d1" />
        <rect x="18" y="80" width="30" height="3" rx="1.5" className="docline d3" />
        <rect x="68" y="80" width="18" height="3" rx="1.5" className="docline d1" />
        <rect x="94" y="80" width="8" height="3" rx="1.5" className="docline d2" />
        <rect x="18" y="88" width="44" height="3" rx="1.5" className="docline d1" />
        <rect x="68" y="88" width="18" height="3" rx="1.5" className="docline d2" />
        <rect x="94" y="88" width="8" height="3" rx="1.5" className="docline d3" />
        <line x1="18" y1="100" x2="102" y2="100" stroke="#E1E5EB" />
        <rect x="18" y="106" width="26" height="3" rx="1.5" className="docline d2" />
        <rect x="80" y="106" width="22" height="3" rx="1.5" className="docline d1" />
        <circle cx="94" cy="128" r="11" fill="none" stroke="#B8923E" strokeWidth="1.5" className="seal" />
        <path d="M94 121 L99 124 L94 127 L89 124 Z" fill="#B8923E" className="seal" />
      </svg>
      <div className="scanbeam" />
      <div className="scanmark">
        {failed ? <AlertCircle size={22} /> : <Check size={22} />}
      </div>
    </div>
  )
}
