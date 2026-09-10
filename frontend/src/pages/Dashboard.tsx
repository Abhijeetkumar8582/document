import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { UploadCloud, Download, ArrowRight, Loader2, AlertCircle, ShieldCheck } from 'lucide-react'
import { api, fmt, type Dashboard as Data, type Engine } from '../api'
import { Notice, PageHeader, Skeleton } from '../components/ui'
import { BarSeries, HBars, Donut } from '../components/charts'

// Fixed hue per engine, validated for colour-vision safety; never reassigned when a bar is empty.
const ENGINE_COLOR: Record<Engine, string> = { text: '#2E6FBE', google_docai: '#D19A2C', llm_vision: '#238F5E', ocr: '#CF4C31' }
const STATUS_COLOR: Record<string, string> = { verified: '#238F5E', needs_review: '#D19A2C' }
const SCALE_COLOR: Record<string, string> = { '4.0': '#2E6FBE', percentage: '#6C4DBF', other: '#8A94A6' }
const SINGLE = '#2E6FBE'

const RANGES = [
  { days: 14, label: '14 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
]

export default function Dashboard() {
  const [days, setDays] = useState(30)
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    api
      .dashboard(days)
      .then((d) => live && setData(d))
      .catch((e) => live && setError(e.message))
    return () => {
      live = false
    }
  }, [days])

  // Keep the queue tiles fresh while anything is running.
  useEffect(() => {
    if (!data || data.queue.processing + data.queue.queued === 0) return
    const t = setInterval(() => api.dashboard(days).then(setData).catch(() => null), 4000)
    return () => clearInterval(t)
  }, [data, days])

  if (error) return <Notice kind="error">{error}</Notice>
  if (!data) return <Skeleton rows={5} />

  const delta = data.added_last_7 - data.added_prev_7
  const reviewPct = data.total_records ? Math.round((data.needs_review / data.total_records) * 100) : 0

  return (
    <div className="mx-auto max-w-6xl">
      <PageHeader
        eyebrow="Dashboard"
        title="The register at a glance"
        action={
          <div className="flex gap-2">
            <a href={api.exportUrl()} className="btn-ghost">
              <Download size={16} /> Export CSV
            </a>
            <Link to="/upload" className="btn-primary">
              <UploadCloud size={16} /> Upload records
            </Link>
          </div>
        }
      />

      {data.total_records === 0 ? (
        <div className="card settle px-6 py-14 text-center">
          <div className="font-display text-lg font-semibold text-ink">Nothing on file yet</div>
          <div className="mx-auto mt-2 max-w-md text-sm text-slate-500">Upload a transcript, a folder, or a ZIP and this page fills in.</div>
          <div className="mt-5">
            <Link to="/upload" className="btn-primary">
              Upload the first record <ArrowRight size={15} />
            </Link>
          </div>
        </div>
      ) : (
        <>
          {/* Headline figures */}
          <div className="settle settle-2 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Records on file" value={fmt.compact(data.total_records)} sub={`${data.institutions} institutions`} />
            <Tile
              label="Added in the last 7 days"
              value={fmt.compact(data.added_last_7)}
              sub={delta === 0 ? 'same as the week before' : `${delta > 0 ? '+' : ''}${delta} vs the week before`}
              tone={delta > 0 ? 'good' : delta < 0 ? 'warn' : undefined}
            />
            <Tile
              label="Awaiting review"
              value={fmt.compact(data.needs_review)}
              sub={`${reviewPct}% of records`}
              tone={data.needs_review > 0 ? 'warn' : 'good'}
              href="/records?status=needs_review"
            />
            <Tile
              label="Average GPA"
              value={data.average_gpa !== null ? data.average_gpa.toFixed(2) : '—'}
              sub={data.average_percentage !== null ? `${data.average_percentage.toFixed(1)}% on marks-based sheets` : '4.0-scale transcripts'}
            />
          </div>

          {/* Intake over time */}
          <section className="settle settle-3 card mt-4">
            <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
              <div>
                <div className="eyebrow">Intake</div>
                <div className="text-sm text-slate-600">Records filed per day</div>
              </div>
              <div className="ml-auto flex overflow-hidden rounded-md border border-line bg-paper-2" role="radiogroup" aria-label="Date range">
                {RANGES.map((r) => (
                  <button
                    key={r.days}
                    role="radio"
                    aria-checked={days === r.days}
                    onClick={() => setDays(r.days)}
                    className={`px-3 py-1 text-xs transition-colors ${days === r.days ? 'bg-ink text-white' : 'text-slate-600 hover:bg-paper'}`}
                  >
                    {r.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="px-3 py-3">
              <BarSeries
                points={data.by_day.map((d) => ({ x: d.date, y: d.count }))}
                color={SINGLE}
                height={180}
                formatX={(iso) => new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                formatY={(n) => `${n} ${n === 1 ? 'record' : 'records'}`}
              />
            </div>
          </section>

          <div className="mt-4 grid gap-4 lg:grid-cols-3">
            {/* Review + scale */}
            <section className="settle card">
              <div className="border-b border-line px-5 py-3">
                <div className="eyebrow">Review status</div>
                <div className="text-sm text-slate-600">Verified vs awaiting a person</div>
              </div>
              <div className="px-5 py-4">
                <Donut
                  slices={data.by_status.map((s) => ({ key: s.key, label: s.label, value: s.count, color: STATUS_COLOR[s.key] }))}
                  center={{ value: `${data.total_records - data.needs_review}`, label: 'verified' }}
                />
                <div className="mt-4 border-t border-line pt-3">
                  <div className="eyebrow mb-2">Grade scale</div>
                  <HBars items={data.by_scale.map((s) => ({ key: s.key, label: s.label, value: s.count, color: SCALE_COLOR[s.key] ?? SCALE_COLOR.other }))} />
                </div>
              </div>
            </section>

            {/* Engine mix */}
            <section className="settle card">
              <div className="border-b border-line px-5 py-3">
                <div className="eyebrow">Read by</div>
                <div className="text-sm text-slate-600">Which engine produced each record</div>
              </div>
              <div className="px-5 py-4">
                <HBars items={data.by_engine.map((e) => ({ key: e.key, label: e.label, value: e.count, color: ENGINE_COLOR[e.key as Engine] ?? '#8A94A6', href: `/records?engine=${e.key}` }))} />
                <div className="mt-4 border-t border-line pt-3 text-xs text-slate-500">
                  Extraction confidence averages{' '}
                  <span className="font-mono text-ink">{data.average_confidence !== null ? Math.round(data.average_confidence * 100) : '—'}%</span> across all records.
                  {data.pii_redacted > 0 && (
                    <span className="mt-1 flex items-center gap-1">
                      <ShieldCheck size={12} className="text-moss" /> {data.pii_redacted} {data.pii_redacted === 1 ? 'record had' : 'records had'} an SSN or birth date removed.
                    </span>
                  )}
                </div>
              </div>
            </section>

            {/* GPA distribution */}
            <section className="settle card">
              <div className="border-b border-line px-5 py-3">
                <div className="eyebrow">GPA distribution</div>
                <div className="text-sm text-slate-600">4.0-scale transcripts only</div>
              </div>
              <div className="px-3 py-3">
                {data.gpa_buckets.some((b) => b.count > 0) ? (
                  <BarSeries points={data.gpa_buckets.map((b) => ({ x: b.label, y: b.count }))} color={SINGLE} height={150} labelEvery={1} formatY={(n) => `${n} ${n === 1 ? 'student' : 'students'}`} />
                ) : (
                  <div className="px-2 py-8 text-center text-sm text-slate-500">No 4.0-scale transcripts yet.</div>
                )}
              </div>
            </section>
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-2">
            {/* Institutions */}
            <section className="settle card">
              <div className="border-b border-line px-5 py-3">
                <div className="eyebrow">Top institutions</div>
                <div className="text-sm text-slate-600">By records on file</div>
              </div>
              <div className="px-5 py-4">
                {data.top_institutions.length ? (
                  <HBars items={data.top_institutions.map((i) => ({ key: i.key, label: i.label, value: i.count, color: SINGLE, href: `/records?q=${encodeURIComponent(i.label)}` }))} />
                ) : (
                  <div className="py-6 text-center text-sm text-slate-500">No institution names found yet.</div>
                )}
              </div>
            </section>

            {/* Queue */}
            <section className="settle card">
              <div className="border-b border-line px-5 py-3">
                <div className="eyebrow">Processing queue</div>
                <div className="text-sm text-slate-600">
                  {data.queue.workers} background {data.queue.workers === 1 ? 'worker' : 'workers'}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3 px-5 py-4">
                <QueueTile n={data.queue.processing} label="Processing" icon={data.queue.processing ? <Loader2 size={14} className="animate-spin text-oxford" /> : null} />
                <QueueTile n={data.queue.queued} label="Waiting" />
                <QueueTile n={data.queue.dead} label="Need attention" tone={data.queue.dead ? 'warn' : undefined} icon={data.queue.dead ? <AlertCircle size={14} className="text-seal" /> : null} />
              </div>
              <div className="border-t border-line px-5 py-2.5 text-xs">
                <Link to="/upload" className="inline-flex items-center gap-1 text-oxford hover:underline">
                  Recent uploads <ArrowRight size={12} />
                </Link>
                {data.queue.running_batches > 0 && <span className="ml-2 text-slate-500">{data.queue.running_batches} running</span>}
              </div>
            </section>

          </div>
        </>
      )}
    </div>
  )
}

function Tile({ label, value, sub, tone, href }: { label: string; value: string; sub?: string; tone?: 'good' | 'warn'; href?: string }) {
  const body = (
    <>
      <div className="eyebrow">{label}</div>
      <div className="mt-2 font-display text-[30px] font-semibold leading-none tracking-tight text-ink">{value}</div>
      {sub && <div className={`mt-2 text-xs ${tone === 'good' ? 'text-moss' : tone === 'warn' ? 'text-[#7A5F1E]' : 'text-slate-500'}`}>{sub}</div>}
    </>
  )
  return href ? (
    <Link to={href} className="card block px-5 py-4 transition-colors hover:border-line-2">
      {body}
    </Link>
  ) : (
    <div className="card px-5 py-4">{body}</div>
  )
}

function QueueTile({ n, label, tone, icon }: { n: number; label: string; tone?: 'warn'; icon?: React.ReactNode }) {
  return (
    <div>
      <div className={`flex items-center gap-1.5 font-display text-2xl font-semibold leading-none ${n === 0 ? 'text-slate-300' : tone === 'warn' ? 'text-seal' : 'text-ink'}`}>
        {n}
        {icon}
      </div>
      <div className="mt-1 eyebrow">{label}</div>
    </div>
  )
}
