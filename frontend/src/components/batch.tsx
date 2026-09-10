import type { Batch, BatchStatus, JobStatus } from '../api'

/** Stacked bar: one colour per job outcome, so a batch's shape is readable at a glance. */
export function BatchBar({ batch }: { batch: Batch }) {
  const t = Math.max(1, batch.total_jobs)
  const c = batch.counts
  const seg = (n: number, cls: string, label: string) =>
    n > 0 ? <div key={label} className={`h-full ${cls}`} style={{ width: `${(n / t) * 100}%` }} title={`${n} ${label}`} /> : null
  return (
    <div className="flex items-center gap-2">
      <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-line">
        {seg(c.done, 'bg-moss', 'filed')}
        {seg(c.skipped, 'bg-moss/40', 'skipped as duplicates')}
        {seg(c.processing, 'bg-oxford animate-pulse', 'processing')}
        {seg(c.failed, 'bg-gilt', 'retrying')}
        {seg(c.dead, 'bg-seal', 'need attention')}
        {seg(c.cancelled, 'bg-slate-400', 'cancelled')}
      </div>
      <span className="w-10 text-right font-mono text-xs text-slate-500">{Math.round((batch.finished_jobs / t) * 100)}%</span>
    </div>
  )
}

const BATCH_TONE: Record<BatchStatus, { label: string; cls: string }> = {
  queued: { label: 'Queued', cls: 'bg-paper text-slate-600 border-line' },
  running: { label: 'Running', cls: 'bg-oxford-soft text-oxford border-oxford/30' },
  completed: { label: 'Completed', cls: 'bg-moss-soft text-moss border-moss/30' },
  attention: { label: 'Needs attention', cls: 'bg-seal-soft text-seal border-seal/30' },
  cancelled: { label: 'Cancelled', cls: 'bg-paper text-slate-500 border-line' },
}

export function BatchStatusChip({ status }: { status: BatchStatus }) {
  const t = BATCH_TONE[status] ?? BATCH_TONE.queued
  return <span className={`inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[11px] tracking-wide ${t.cls}`}>{t.label}</span>
}

const JOB_TONE: Record<JobStatus, { label: string; cls: string }> = {
  queued: { label: 'Waiting', cls: 'bg-paper text-slate-600 border-line' },
  processing: { label: 'Processing', cls: 'bg-oxford-soft text-oxford border-oxford/30' },
  failed: { label: 'Retrying', cls: 'bg-gilt-soft text-[#7A5F1E] border-gilt/40' },
  done: { label: 'Filed', cls: 'bg-moss-soft text-moss border-moss/30' },
  skipped: { label: 'Duplicate', cls: 'bg-moss-soft/60 text-moss border-moss/20' },
  dead: { label: 'Needs attention', cls: 'bg-seal-soft text-seal border-seal/30' },
  cancelled: { label: 'Cancelled', cls: 'bg-paper text-slate-500 border-line' },
}

export function JobStatusChip({ status }: { status: JobStatus }) {
  const t = JOB_TONE[status] ?? JOB_TONE.queued
  return <span className={`inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[11px] tracking-wide ${t.cls}`}>{t.label}</span>
}
