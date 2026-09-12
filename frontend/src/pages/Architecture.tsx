import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, Check, Minus, ShieldCheck, Database, Cloud, Cpu, FileSearch, ScanLine, Layers, UploadCloud, ListChecks } from 'lucide-react'
import { api, fmt, type EngineStatus, type QueueSummary, type RecordDetail, type StorageStatus } from '../api'
import { Notice, PageHeader, Skeleton } from '../components/ui'

type Live = { engines: EngineStatus; storage: StorageStatus; queue: QueueSummary; latest: RecordDetail | null }

export default function Architecture() {
  const [live, setLive] = useState<Live | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const [engines, storage, queue, page] = await Promise.all([api.engines(), api.storage(), api.queueSummary(), api.list({ page_size: 1 })])
        const latest = page.items[0] ? await api.get(page.items[0].id) : null
        if (alive) setLive({ engines, storage, queue, latest })
      } catch (e) {
        if (alive) setError((e as Error).message)
      }
    }
    load()
    const t = setInterval(load, 5000)
    return () => {
      alive = false
      clearInterval(t)
    }
  }, [])

  if (error && !live) return <Notice kind="error">{error}</Notice>
  if (!live) return <Skeleton rows={5} />

  const { engines, storage, queue, latest } = live
  const storageLabel = storage.backend === 's3' ? `S3 · ${storage.bucket}` : 'Local disk'
  const threshold = Math.round((engines.google_docai.threshold ?? 0.7) * 100)

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader eyebrow="Architecture" title="What happens to a document" />

      {/* Flow */}
      <section className="settle settle-2 card overflow-x-auto">
        <div className="flex items-center justify-between border-b border-line px-5 py-3">
          <div>
            <div className="eyebrow">The path</div>
            <div className="text-sm text-slate-600">Six stages, left to right. Badges show the live state of each one.</div>
          </div>
          <span className="font-mono text-[11px] text-slate-400">refreshes every 5s</span>
        </div>
        <div className="min-w-[880px] px-5 py-6">
          <Flow
            stages={[
              { icon: UploadCloud, title: 'Browser', sub: 'Upload page', badge: 'presigned POST', tone: 'ok', lines: ['File never passes through the API', 'Folders and ZIPs become batches'] },
              { icon: storage.backend === 's3' ? Cloud : Database, title: 'Storage', sub: storageLabel, badge: storage.backend === 's3' ? 'private bucket' : 'signed links', tone: 'ok', lines: [`Links expire after ${Math.round(storage.presign_expires / 60)} min`, `Up to ${Math.round(storage.max_bytes / 1048576)} MB per file`] },
              { icon: Layers, title: 'Queue', sub: `${queue.workers} background ${queue.workers === 1 ? 'worker' : 'workers'}`, badge: queue.processing ? `${queue.processing} processing` : queue.queued ? `${queue.queued} waiting` : 'idle', tone: queue.dead ? 'warn' : 'ok', lines: ['Job row committed before 202', 'Leases, retries with backoff', queue.dead ? `${queue.dead} need attention` : 'Every file reaches a terminal state'] },
              { icon: FileSearch, title: 'Read', sub: 'Engine cascade', badge: `${[engines.text, engines.google_docai, engines.llm_vision, engines.ocr].filter((e) => e.ready).length} of 4 ready`, tone: engines.google_docai.ready || engines.llm_vision.ready ? 'ok' : 'warn', lines: ['Text layer first', `Document AI kept at ≥ ${threshold}%`, 'Local LLM Cloud page by page'] },
              { icon: Cpu, title: 'Parse', sub: 'Fields and courses', badge: 'PII redacted', tone: 'ok', lines: ['SSN and birth date removed', 'US 4.0 scale, credits, quality points', 'Confidence score per record'] },
              { icon: ListChecks, title: 'Register', sub: 'Record on file', badge: 'audited', tone: 'ok', lines: ['Verified or Needs review stamp', 'Every view, edit, download logged', 'Dashboard, CSV export'] },
            ]}
          />
        </div>
      </section>

      <div className="mt-4 grid gap-4 lg:grid-cols-5">
        {/* Engine cascade */}
        <section className="settle card lg:col-span-3">
          <div className="border-b border-line px-5 py-3">
            <div className="eyebrow">How a page gets read</div>
            <div className="text-sm text-slate-600">Tried in this order. The first engine that produces usable text wins.</div>
          </div>
          <ol className="divide-y divide-line">
            <Step n={1} ready={engines.text.ready} icon={FileSearch} title="Text layer" detail="Digital PDFs, Word and text files are read directly. Free, exact, and used whenever the PDF has real text.">
              Always on
            </Step>
            <Step n={2} ready={engines.google_docai.ready} icon={Cloud} title="Google Document AI" detail={`Scans and photos go to your Document AI processor. The result is kept only if its mean token confidence is at least ${threshold}%; below that it is discarded and the next engine takes over.`}>
              {engines.google_docai.ready ? `Ready · gate ${threshold}%` : 'Not configured'}
            </Step>
            <Step n={3} ready={engines.llm_vision.ready} icon={Cpu} title="Local LLM Cloud" detail="Each page is rendered to an image and sent to Gemini with a strict JSON schema. It returns the transcription plus the fields and course rows, which take precedence over the regex parser.">
              {engines.llm_vision.ready ? `Ready · ${engines.llm_vision.model}` : 'Not configured'}
            </Step>
            <Step n={4} ready={engines.ocr.ready} icon={ScanLine} title="Local OCR" detail="Tesseract on this server, used only when no cloud engine is available. Plain text, no confidence score.">
              {engines.ocr.ready ? 'Ready' : 'Not installed'}
            </Step>
          </ol>
        </section>

        {/* Latest journey */}
        <section className="settle card lg:col-span-2">
          <div className="border-b border-line px-5 py-3">
            <div className="eyebrow">Most recent document</div>
            <div className="text-sm text-slate-600">The steps the pipeline actually took</div>
          </div>
          {latest ? (
            <div className="px-5 py-4">
              <Link to={`/records/${latest.id}`} className="font-medium text-ink hover:underline">
                {latest.student_name ?? 'Unnamed'}
              </Link>
              <div className="font-mono text-xs text-slate-500">
                {latest.file_name} · {fmt.timeAgo(latest.created_at)}
              </div>
              <ol className="mt-3 space-y-2 border-l-2 border-line pl-4 text-sm text-slate-700">
                {latest.engine_notes.map((n, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="font-mono text-xs text-slate-400">{i + 1}</span>
                    <span>{n}</span>
                  </li>
                ))}
                <li className="flex gap-3">
                  <span className="font-mono text-xs text-slate-400">{latest.engine_notes.length + 1}</span>
                  <span>
                    Parsed {latest.subject_count} {latest.subject_count === 1 ? 'course' : 'courses'}, {Math.round(latest.confidence * 100)}% of fields found
                    {latest.pii_redacted ? ', an SSN or birth date removed' : ''}. Stamped <b>{latest.review_status === 'verified' ? 'Verified' : 'Needs review'}</b>.
                  </span>
                </li>
              </ol>
            </div>
          ) : (
            <div className="px-5 py-10 text-center text-sm text-slate-500">
              Nothing on file yet.{' '}
              <Link to="/upload" className="text-oxford hover:underline">
                Upload a document
              </Link>{' '}
              and its journey appears here.
            </div>
          )}
        </section>
      </div>

      {/* Guarantees */}
      <section className="settle mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-4">
        <Guarantee icon={UploadCloud} title="Durable before acknowledged">The file is in storage and its job row committed before the browser hears back. Closing the tab changes nothing.</Guarantee>
        <Guarantee icon={Layers} title="Nothing missed">Workers hold a lease and heartbeat while reading. A silent worker loses the job to another; a batch finishes only when every file is filed or explained.</Guarantee>
        <Guarantee icon={Check} title="Filed once">Identical bytes are recognised by content hash and linked to the existing record instead of creating a twin.</Guarantee>
        <Guarantee icon={ShieldCheck} title="FERPA handling">SSNs and birth dates are removed before anything is stored. Every view, edit, preview, download and export is written to the audit log.</Guarantee>
      </section>

      <div className="settle mt-6 text-xs text-slate-500">
        Full design notes, including the job state machine and how to scale workers across machines, are in <span className="font-mono">docs/ARCHITECTURE.md</span> in the repository.
      </div>
    </div>
  )
}

type Stage = { icon: typeof Cloud; title: string; sub: string; badge: string; tone: 'ok' | 'warn'; lines: string[] }

/** Six boxes joined by arrows. Drawn with plain flex so it stays crisp at any width and needs no library. */
function Flow({ stages }: { stages: Stage[] }) {
  return (
    <ol className="flex items-stretch gap-2">
      {stages.map((s, i) => (
        <li key={s.title} className="flex min-w-0 flex-1 items-stretch gap-2">
          <div className="flex min-w-0 flex-1 flex-col rounded-md border border-line bg-paper-2 p-3">
            <div className="flex items-center gap-2">
              <span className="rounded-md bg-ink p-1.5 text-white">
                <s.icon size={14} />
              </span>
              <div className="min-w-0">
                <div className="truncate text-sm font-semibold text-ink">{s.title}</div>
                <div className="truncate font-mono text-[10.5px] text-slate-500">{s.sub}</div>
              </div>
            </div>
            <span className={`mt-2 inline-flex w-fit rounded-full border px-2 py-0.5 font-mono text-[10.5px] ${s.tone === 'ok' ? 'border-moss/30 bg-moss-soft text-moss' : 'border-gilt/40 bg-gilt-soft text-[#7A5F1E]'}`}>
              {s.badge}
            </span>
            <ul className="mt-2 space-y-1 text-[11.5px] leading-4 text-slate-600">
              {s.lines.map((l) => (
                <li key={l} className="flex gap-1.5">
                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-400" />
                  <span>{l}</span>
                </li>
              ))}
            </ul>
          </div>
          {i < stages.length - 1 && (
            <div className="flex shrink-0 items-center text-slate-400" aria-hidden="true">
              <ArrowRight size={16} />
            </div>
          )}
        </li>
      ))}
    </ol>
  )
}

function Step({ n, ready, icon: Icon, title, detail, children }: { n: number; ready: boolean; icon: typeof Cloud; title: string; detail: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-4 px-5 py-4">
      <div className="flex w-8 shrink-0 flex-col items-center gap-1">
        <span className="font-mono text-xs text-slate-400">{n}</span>
        <span className={`rounded-full p-1 ${ready ? 'bg-moss-soft text-moss' : 'bg-paper text-slate-400'}`}>{ready ? <Check size={12} /> : <Minus size={12} />}</span>
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink">
            <Icon size={14} className="text-slate-500" /> {title}
          </span>
          <span className={`font-mono text-[11px] ${ready ? 'text-moss' : 'text-slate-400'}`}>{children}</span>
        </div>
        <p className="mt-1 max-w-[62ch] text-sm text-slate-600">{detail}</p>
      </div>
    </li>
  )
}

function Guarantee({ icon: Icon, title, children }: { icon: typeof Cloud; title: string; children: React.ReactNode }) {
  return (
    <div className="card px-4 py-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-ink">
        <Icon size={15} className="text-oxford" /> {title}
      </div>
      <p className="mt-1.5 text-[13px] leading-5 text-slate-600">{children}</p>
    </div>
  )
}
