import { useRef, useState, type ReactNode } from 'react'
import { BAND, STATUS, T } from '../theme'
import type { Band, CaseStatus, Transition } from '../types'

export function BandTag({ band, score }: { band: Band; score?: number }) {
  return (
    <span className="band" title="Deterministic priority band">
      <i style={{ background: BAND[band].color }} />
      {band}
      {score != null && <span className="muted num" style={{ fontWeight: 400 }}>{score.toFixed(0)}</span>}
    </span>
  )
}

export function StatusTag({ status }: { status: CaseStatus | 'RECORDED' | 'CASE' }) {
  if (status === 'RECORDED') return <span className="status muted" title="Recorded for statistics, not queued for verification">Recorded</span>
  if (status === 'CASE') return <span className="status info">Case</span>
  const s = STATUS[status]
  return <span className={`status ${s.tone}`}>{s.label}</span>
}

export function TransitionTag({ t }: { t: Transition }) {
  const x = T[t]
  return (
    <span className="row" style={{ gap: 6, display: 'inline-flex' }}>
      <span className="swatch" style={{ background: x?.color ?? '#898781' }} />
      {x?.label ?? t}
    </span>
  )
}

export function Panel({
  title,
  sub,
  right,
  children,
  pad = true,
  style,
}: {
  title?: ReactNode
  sub?: ReactNode
  right?: ReactNode
  children: ReactNode
  pad?: boolean
  style?: React.CSSProperties
}) {
  return (
    <section className="panel" style={style}>
      {(title || right) && (
        <header>
          <h2>{title}</h2>
          {sub && <span className="sub">{sub}</span>}
          {right && <span className="right row">{right}</span>}
        </header>
      )}
      <div className={pad ? 'body' : undefined}>{children}</div>
    </section>
  )
}

/** Before/after swipe comparison of two co-registered images. */
export function Compare({ before, after, labels }: { before: string; after: string; labels: [string, string] }) {
  const [pos, setPos] = useState(50)
  const box = useRef<HTMLDivElement>(null)
  const drag = useRef(false)
  const move = (clientX: number) => {
    const r = box.current?.getBoundingClientRect()
    if (!r) return
    setPos(Math.max(0, Math.min(100, ((clientX - r.left) / r.width) * 100)))
  }
  return (
    <div
      ref={box}
      className="compare"
      onPointerDown={(e) => {
        drag.current = true
        ;(e.target as HTMLElement).setPointerCapture?.(e.pointerId)
        move(e.clientX)
      }}
      onPointerMove={(e) => drag.current && move(e.clientX)}
      onPointerUp={() => (drag.current = false)}
      role="slider"
      aria-label="Before / after comparison"
      aria-valuenow={Math.round(pos)}
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') setPos((p) => Math.max(0, p - 5))
        if (e.key === 'ArrowRight') setPos((p) => Math.min(100, p + 5))
      }}
    >
      <img src={after} alt={labels[1]} draggable={false} />
      <img src={before} alt={labels[0]} draggable={false} style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }} />
      <div className="handle" style={{ left: `${pos}%` }} />
      <span className="tag" style={{ left: 6 }}>{labels[0]}</span>
      <span className="tag" style={{ right: 6 }}>{labels[1]}</span>
    </div>
  )
}

export function Kpi({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="kpi">
      <div className="l">{label}</div>
      <div className="v num">{value}</div>
      {sub && <div className="s">{sub}</div>}
    </div>
  )
}

export function Loading({ what = 'Loading' }: { what?: string }) {
  return <p className="muted" style={{ padding: 16 }}>{what}…</p>
}
