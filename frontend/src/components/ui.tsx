import type { ReactNode } from 'react'
import { AlertCircle, CheckCircle2, Cloud, FileText, ScanLine, ShieldCheck, Sparkles } from 'lucide-react'
import { ENGINE_LABEL, type Engine, type ReviewStatus } from '../api'

export function PageHeader({ eyebrow, title, action }: { eyebrow: string; title: string; action?: ReactNode }) {
  return (
    <div className="settle mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1 className="mt-1 font-display text-[28px] font-semibold leading-tight tracking-tight text-ink">{title}</h1>
      </div>
      {action}
    </div>
  )
}

export function Stamp({ status, size = 'sm' }: { status: ReviewStatus; size?: 'sm' | 'lg' }) {
  const verified = status === 'verified'
  return (
    <span className={`stamp ${size === 'lg' ? 'stamp-lg' : ''} ${verified ? 'stamp-verified' : 'stamp-review'}`}>
      {verified ? 'Verified' : 'Needs review'}
    </span>
  )
}

const ENGINE_STYLE: Record<Engine, { icon: typeof FileText; cls: string }> = {
  text: { icon: FileText, cls: 'border-line bg-paper text-slate-700' },
  google_docai: { icon: Cloud, cls: 'border-oxford/30 bg-oxford-soft text-oxford' },
  llm_vision: { icon: Sparkles, cls: 'border-gilt/40 bg-gilt-soft text-[#7A5F1E]' },
  ocr: { icon: ScanLine, cls: 'border-line bg-paper text-slate-700' },
}

/** Which engine read the file. The tag every record carries so nobody has to guess. */
export function EngineTag({
  engine,
  confidence,
  model,
  compact,
}: {
  engine: Engine
  confidence?: number | null
  model?: string | null
  compact?: boolean
}) {
  const { icon: Icon, cls } = ENGINE_STYLE[engine] ?? ENGINE_STYLE.text
  const label = ENGINE_LABEL[engine] ?? engine
  const extra =
    engine === 'google_docai' && confidence !== null && confidence !== undefined
      ? `${Math.round(confidence * 100)}%`
      : engine === 'llm_vision' && model
        ? model
        : null
  return (
    <span
      className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 font-mono text-[11px] tracking-wide ${cls}`}
      title={`Read by ${label}${extra ? ` (${extra})` : ''}`}
    >
      <Icon size={12} strokeWidth={2} />
      {compact ? label : `${label}${extra ? ` · ${extra}` : ''}`}
    </span>
  )
}

export function PiiBadge() {
  return (
    <span
      className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-moss/30 bg-moss-soft px-2 py-0.5 font-mono text-[11px] tracking-wide text-moss"
      title="A Social Security number or date of birth was found and removed before storage."
    >
      <ShieldCheck size={12} strokeWidth={2} /> PII redacted
    </span>
  )
}

export function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  const tone = pct >= 75 ? 'bg-moss' : pct >= 45 ? 'bg-gilt' : 'bg-seal'
  return (
    <div className="flex items-center gap-2" title={`Field extraction confidence ${pct}%`}>
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-line">
        <div className={`h-full ${tone}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-xs text-slate-500">{pct}%</span>
    </div>
  )
}

export function Notice({ kind, children }: { kind: 'error' | 'success' | 'info'; children: ReactNode }) {
  const styles = {
    error: 'border-seal/30 bg-seal-soft text-seal',
    success: 'border-moss/30 bg-moss-soft text-moss',
    info: 'border-oxford/20 bg-oxford-soft text-oxford',
  }[kind]
  const Icon = kind === 'error' ? AlertCircle : kind === 'success' ? CheckCircle2 : ShieldCheck
  return (
    <div role={kind === 'error' ? 'alert' : 'status'} className={`flex items-start gap-2.5 rounded-md border px-3.5 py-3 text-sm ${styles}`}>
      <Icon size={16} className="mt-0.5 shrink-0" />
      <div>{children}</div>
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="card settle px-6 py-14 text-center">
      <div className="font-display text-lg font-semibold text-ink">{title}</div>
      {children && <div className="mx-auto mt-2 max-w-md text-sm text-slate-500">{children}</div>}
    </div>
  )
}

export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="card divide-y divide-line">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-6 px-4 py-4">
          <div className="h-3 w-40 animate-pulse rounded bg-line" />
          <div className="h-3 w-56 animate-pulse rounded bg-line" />
          <div className="ml-auto h-3 w-16 animate-pulse rounded bg-line" />
        </div>
      ))}
    </div>
  )
}
