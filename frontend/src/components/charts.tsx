import { useId, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'

/*
 * Small inline-SVG charts. Rules they follow: bars ≤ 24px with a 4px rounded data end and a square
 * baseline; a 2px surface gap between neighbours; hairline gridlines; text in text tokens, never the
 * series colour; every mark has a hover tooltip; values are direct-labelled only where they matter.
 */

const TEXT = '#374151'
const MUTED = '#6B7280'
const GRID = '#E1E5EB'

function niceMax(max: number): number {
  if (max <= 5) return 5
  const p = 10 ** Math.floor(Math.log10(max))
  const m = max / p
  const step = m <= 1 ? 1 : m <= 2 ? 2 : m <= 5 ? 5 : 10
  return step * p
}

/** Vertical bars over an ordered category axis (days, buckets). One series, so no legend. */
export function BarSeries({
  points,
  color,
  height = 180,
  labelEvery,
  formatX = (x) => x,
  formatY = (n) => String(n),
}: {
  points: { x: string; y: number }[]
  color: string
  height?: number
  labelEvery?: number
  formatX?: (x: string) => string
  formatY?: (n: number) => string
}) {
  const [hover, setHover] = useState<number | null>(null)
  const id = useId()
  const W = 720
  const padL = 34
  const padR = 8
  const padT = 14
  const padB = 24
  const innerW = W - padL - padR
  const innerH = height - padT - padB
  const n = Math.max(points.length, 1)
  const slot = innerW / n
  const barW = Math.min(24, Math.max(3, slot - 2))
  const yMax = niceMax(Math.max(1, ...points.map((p) => p.y)))
  const ticks = [0, yMax / 2, yMax]
  const every = labelEvery ?? Math.max(1, Math.ceil(n / 8))
  const peak = points.reduce((best, p, i) => (p.y > (points[best]?.y ?? -1) ? i : best), 0)

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${height}`} className="block h-auto w-full" role="img" aria-labelledby={`${id}-t`}>
        <title id={`${id}-t`}>Bar chart, {points.length} bars</title>
        {ticks.map((t) => {
          const y = padT + innerH - (t / yMax) * innerH
          return (
            <g key={t}>
              <line x1={padL} x2={W - padR} y1={y} y2={y} stroke={GRID} strokeWidth={1} />
              <text x={padL - 6} y={y + 3.5} textAnchor="end" fontSize={10} fontFamily="IBM Plex Mono, monospace" fill={MUTED}>
                {t}
              </text>
            </g>
          )
        })}
        {points.map((p, i) => {
          const h = (p.y / yMax) * innerH
          const x = padL + i * slot + (slot - barW) / 2
          const y = padT + innerH - h
          const r = Math.min(4, barW / 2, h)
          const active = hover === i
          return (
            <g key={p.x} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              {/* hit target bigger than the mark */}
              <rect x={padL + i * slot} y={padT} width={slot} height={innerH} fill="transparent" />
              {h > 0 && (
                <path
                  d={`M${x},${y + r} a${r},${r} 0 0 1 ${r},-${r} h${barW - 2 * r} a${r},${r} 0 0 1 ${r},${r} v${h - r} h-${barW} z`}
                  fill={color}
                  opacity={hover === null || active ? 1 : 0.55}
                />
              )}
              {(i === peak && p.y > 0 && !active) && (
                <text x={x + barW / 2} y={y - 4} textAnchor="middle" fontSize={10} fontFamily="IBM Plex Mono, monospace" fill={TEXT}>
                  {p.y}
                </text>
              )}
              {i % every === 0 && (
                <text x={padL + i * slot + slot / 2} y={height - 8} textAnchor="middle" fontSize={10} fontFamily="IBM Plex Mono, monospace" fill={MUTED}>
                  {formatX(p.x)}
                </text>
              )}
            </g>
          )
        })}
        <line x1={padL} x2={W - padR} y1={padT + innerH} y2={padT + innerH} stroke={GRID} strokeWidth={1} />
      </svg>
      {hover !== null && points[hover] && (
        <Tooltip left={((padL + hover * slot + slot / 2) / W) * 100}>
          <div className="font-medium text-ink">{formatX(points[hover].x)}</div>
          <div className="text-slate-600">{formatY(points[hover].y)}</div>
        </Tooltip>
      )}
    </div>
  )
}

/** Horizontal bars with the label on the left and the value at the tip. Colour per row is identity. */
export function HBars({ items }: { items: { key: string; label: string; value: number; color: string; href?: string }[] }) {
  const max = Math.max(1, ...items.map((i) => i.value))
  const total = items.reduce((a, i) => a + i.value, 0)
  return (
    <ul className="space-y-2">
      {items.map((it) => {
        const pct = total ? Math.round((it.value / total) * 100) : 0
        const row = (
          <div className="group flex items-center gap-3" title={`${it.label}: ${it.value} (${pct}%)`}>
            <span className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: it.color }} aria-hidden="true" />
            <span className="w-32 shrink-0 truncate text-sm text-slate-700 group-hover:text-ink">{it.label}</span>
            <div className="h-3 min-w-0 flex-1 overflow-hidden rounded-r bg-paper">
              <div className="h-full rounded-r transition-[width]" style={{ width: `${(it.value / max) * 100}%`, background: it.color, opacity: it.value ? 1 : 0 }} />
            </div>
            <span className="w-16 shrink-0 text-right font-mono text-xs text-slate-700">
              {it.value} <span className="text-slate-400">{total ? `${pct}%` : ''}</span>
            </span>
          </div>
        )
        return <li key={it.key}>{it.href ? <Link to={it.href}>{row}</Link> : row}</li>
      })}
    </ul>
  )
}

/** Donut for a two- or three-way split, with the headline in the middle and a legend beside it. */
export function Donut({ slices, center }: { slices: { key: string; label: string; value: number; color: string }[]; center: { value: string; label: string } }) {
  const [hover, setHover] = useState<string | null>(null)
  const total = slices.reduce((a, s) => a + s.value, 0)
  const R = 44
  const r = 30
  const C = 2 * Math.PI * ((R + r) / 2)
  let offset = 0
  return (
    <div className="flex items-center gap-5">
      <svg viewBox="0 0 100 100" width={110} height={110} role="img" aria-label={`${center.value} ${center.label} of ${total}`}>
        <circle cx={50} cy={50} r={(R + r) / 2} fill="none" stroke="#E8EEF6" strokeWidth={R - r} />
        {total > 0 &&
          slices.map((s) => {
            const len = (s.value / total) * C
            const gap = slices.length > 1 && s.value > 0 ? 2 : 0
            const el = (
              <circle
                key={s.key}
                cx={50}
                cy={50}
                r={(R + r) / 2}
                fill="none"
                stroke={s.color}
                strokeWidth={R - r}
                strokeDasharray={`${Math.max(0, len - gap)} ${C - Math.max(0, len - gap)}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 50 50)"
                opacity={hover === null || hover === s.key ? 1 : 0.45}
                onMouseEnter={() => setHover(s.key)}
                onMouseLeave={() => setHover(null)}
              />
            )
            offset += len
            return el
          })}
        <text x={50} y={48} textAnchor="middle" fontSize={16} fontWeight={600} fontFamily="IBM Plex Sans, sans-serif" fill="#111827">
          {center.value}
        </text>
        <text x={50} y={61} textAnchor="middle" fontSize={8} fontFamily="IBM Plex Mono, monospace" fill={MUTED}>
          {center.label.toUpperCase()}
        </text>
      </svg>
      <ul className="space-y-1.5 text-sm">
        {slices.map((s) => (
          <li key={s.key} className={`flex items-center gap-2 ${hover && hover !== s.key ? 'opacity-50' : ''}`} onMouseEnter={() => setHover(s.key)} onMouseLeave={() => setHover(null)}>
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} aria-hidden="true" />
            <span className="text-slate-700">{s.label}</span>
            <span className="font-mono text-xs text-slate-500">
              {s.value}
              {total ? ` · ${Math.round((s.value / total) * 100)}%` : ''}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function Tooltip({ left, children }: { left: number; children: ReactNode }) {
  return (
    <div className="pointer-events-none absolute top-1 z-10 -translate-x-1/2 rounded-md border border-line bg-paper-2 px-2.5 py-1.5 text-xs shadow-lift" style={{ left: `${left}%` }}>
      {children}
    </div>
  )
}
