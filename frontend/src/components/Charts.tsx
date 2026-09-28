import { useState, type ReactNode } from 'react'

// Small, dependency-free chart primitives following the dataviz method:
// thin marks, one axis, recessive grid, hover tooltip on every mark,
// text in ink tokens (never the series colour), legends for >= 2 series.

interface Tip {
  x: number
  y: number
  content: ReactNode
}

function useTip() {
  const [tip, setTip] = useState<Tip | null>(null)
  const node = tip ? (
    <div className="tooltip" style={{ left: tip.x + 12, top: tip.y + 12 }}>
      {tip.content}
    </div>
  ) : null
  return { setTip, node }
}

export interface BarItem {
  key: string
  label: string
  value: number
  color: string
  detail?: ReactNode
}

/** Horizontal bar list: magnitude by category, labelled, sorted by the caller. */
export function BarList({ items, unit, max }: { items: BarItem[]; unit: string; max?: number }) {
  const { setTip, node } = useTip()
  const top = max ?? Math.max(1e-9, ...items.map((i) => i.value))
  if (!items.length) return <p className="muted small">No data yet.</p>
  return (
    <div className="barlist">
      {items.map((i) => (
        <div
          className="r"
          key={i.key}
          onMouseMove={(e) =>
            setTip({
              x: e.clientX,
              y: e.clientY,
              content: (
                <>
                  <b>{i.label}</b>
                  <br />
                  {i.value.toLocaleString(undefined, { maximumFractionDigits: 2 })} {unit}
                  {i.detail ? <div className="muted">{i.detail}</div> : null}
                </>
              ),
            })
          }
          onMouseLeave={() => setTip(null)}
        >
          <span className="lab row" title={i.label}>
            <span className="swatch" style={{ background: i.color }} />
            {i.label}
          </span>
          <span className="track">
            <span className="fill" style={{ display: 'block', width: `${(100 * i.value) / top}%`, background: i.color }} />
          </span>
          <span className="num small" style={{ textAlign: 'right' }}>
            {i.value.toLocaleString(undefined, { maximumFractionDigits: 1 })}
          </span>
        </div>
      ))}
      {node}
    </div>
  )
}

export interface Series {
  key: string
  label: string
  color: string
  values: (number | null)[]
}

/** Line chart with shared x categories, crosshair + tooltip, direct end labels. */
export function LineChart({
  x,
  series,
  height = 190,
  yFormat = (v: number) => `${(v * 100).toFixed(0)}%`,
  yMax,
}: {
  x: string[]
  series: Series[]
  height?: number
  yFormat?: (v: number) => string
  yMax?: number
}) {
  const [hover, setHover] = useState<number | null>(null)
  const W = 560
  const H = height
  const m = { l: 40, r: 96, t: 10, b: 24 }
  const all = series.flatMap((s) => s.values.filter((v): v is number => v != null))
  const top = yMax ?? niceMax(Math.max(1e-9, ...all))
  const xs = (i: number) => m.l + (x.length === 1 ? 0 : (i * (W - m.l - m.r)) / (x.length - 1))
  const ys = (v: number) => H - m.b - (v / top) * (H - m.t - m.b)
  const ticks = [0, top / 2, top]
  // Direct end labels, nudged apart so they never overlap (min 13 px).
  const labelY: Record<string, number> = {}
  const ends = series
    .map((s) => {
      const last = [...s.values].reverse().find((v) => v != null)
      return { key: s.key, y: last == null ? H - m.b : ys(last) }
    })
    .sort((a, b) => a.y - b.y)
  ends.forEach((e, i) => {
    labelY[e.key] = i === 0 ? e.y : Math.max(e.y, labelY[ends[i - 1].key] + 13)
  })
  return (
    <div className="chart" style={{ position: 'relative' }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        onMouseMove={(e) => {
          const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect()
          const px = ((e.clientX - r.left) / r.width) * W
          let best = 0
          x.forEach((_, i) => {
            if (Math.abs(xs(i) - px) < Math.abs(xs(best) - px)) best = i
          })
          setHover(best)
        }}
        onMouseLeave={() => setHover(null)}
        role="img"
      >
        {ticks.map((t) => (
          <g key={t}>
            <line className={t === 0 ? 'baseline' : 'gridline'} x1={m.l} x2={W - m.r} y1={ys(t)} y2={ys(t)} />
            <text className="tick" x={m.l - 6} y={ys(t) + 3} textAnchor="end">
              {yFormat(t)}
            </text>
          </g>
        ))}
        {x.map((lab, i) => (
          <text key={lab} className="tick" x={xs(i)} y={H - 6} textAnchor="middle">
            {lab}
          </text>
        ))}
        {hover != null && <line x1={xs(hover)} x2={xs(hover)} y1={m.t} y2={H - m.b} stroke="var(--axis)" />}
        {series.map((s) => {
          const pts = s.values.map((v, i) => (v == null ? null : ([xs(i), ys(v)] as const)))
          const d = pts.reduce((acc, p, i) => (p ? acc + `${acc && pts[i - 1] ? 'L' : 'M'}${p[0]},${p[1]}` : acc), '')
          const lastIdx = s.values.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0).pop()
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />
              {pts.map((p, i) =>
                p ? (
                  <circle key={i} cx={p[0]} cy={p[1]} r={hover === i ? 4.5 : 2.5} fill={s.color} stroke="var(--surface)" strokeWidth={1.5} />
                ) : null,
              )}
              {lastIdx != null && series.length <= 4 && (
                <text x={xs(lastIdx) + 8} y={labelY[s.key] + 4} style={{ fontSize: 11, fill: 'var(--ink-2)' }}>
                  {s.label}
                </text>
              )}
            </g>
          )
        })}
      </svg>
      {hover != null && (
        <div className="tooltip" style={{ position: 'absolute', left: `${(xs(hover) / W) * 100}%`, top: 0, transform: 'translateX(12px)' }}>
          <b>{x[hover]}</b>
          {series.map((s) => (
            <div key={s.key} className="row" style={{ gap: 6 }}>
              <span className="swatch" style={{ background: s.color }} />
              <span className="ink2">{s.label}</span>
              <span className="num right">{s.values[hover] == null ? '—' : yFormat(s.values[hover] as number)}</span>
            </div>
          ))}
        </div>
      )}
      {series.length >= 2 && <Legend items={series.map((s) => ({ label: s.label, color: s.color }))} />}
    </div>
  )
}

/** Stacked horizontal bar per row (e.g. verification outcomes per class). */
export function StackedRows({
  rows,
  segments,
}: {
  rows: { key: string; label: string; values: Record<string, number> }[]
  segments: { key: string; label: string; color: string }[]
}) {
  const { setTip, node } = useTip()
  const max = Math.max(1, ...rows.map((r) => segments.reduce((a, s) => a + (r.values[s.key] ?? 0), 0)))
  return (
    <div className="stack" style={{ gap: 7 }}>
      {rows.map((r) => {
        const total = segments.reduce((a, s) => a + (r.values[s.key] ?? 0), 0)
        return (
          <div key={r.key} style={{ display: 'grid', gridTemplateColumns: '150px 1fr 40px', gap: 8, alignItems: 'center' }}>
            <span className="small" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {r.label}
            </span>
            <span style={{ display: 'flex', gap: 2, height: 10 }}>
              {segments.map((s, i) => {
                const v = r.values[s.key] ?? 0
                if (!v) return null
                const last = segments.slice(i + 1).every((n) => !(r.values[n.key] ?? 0))
                return (
                  <span
                    key={s.key}
                    style={{ width: `${(100 * v) / max}%`, background: s.color, borderRadius: last ? '0 4px 4px 0' : 0 }}
                    onMouseMove={(e) =>
                      setTip({ x: e.clientX, y: e.clientY, content: <><b>{r.label}</b><br />{s.label}: {v}</> })
                    }
                    onMouseLeave={() => setTip(null)}
                  />
                )
              })}
            </span>
            <span className="num small" style={{ textAlign: 'right' }}>{total.toLocaleString(undefined, { maximumFractionDigits: 1 })}</span>
          </div>
        )
      })}
      <Legend items={segments} />
      {node}
    </div>
  )
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="row wrap small ink2" style={{ gap: 12, marginTop: 6 }}>
      {items.map((i) => (
        <span key={i.label} className="row" style={{ gap: 5 }}>
          <span className="swatch" style={{ background: i.color }} />
          {i.label}
        </span>
      ))}
    </div>
  )
}

function niceMax(v: number) {
  const p = Math.pow(10, Math.floor(Math.log10(v)))
  const n = v / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * p
}
