import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../app-context'
import { BandTag, Loading, Panel, StatusTag } from '../components/ui'
import { T, TRANSITIONS, fmtDate, fmtHa, STATUS } from '../theme'
import type { Aoi, CaseFC, CaseProps } from '../types'

export function CaseTable({ rows, compact = false }: { rows: CaseProps[]; compact?: boolean }) {
  const nav = useNavigate()
  if (!rows.length) return <p className="muted" style={{ padding: 12, margin: 0 }}>No cases match.</p>
  return (
    <table className="data">
      <thead>
        <tr>
          <th>Priority</th>
          <th>Case</th>
          <th>Suspected change</th>
          <th className="num">Area (ha)</th>
          {!compact && <th className="num">Conf.</th>}
          {!compact && <th>District</th>}
          <th>Observed</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((c) => (
          <tr key={c.case_id} className="click" onClick={() => nav(`/cases/${c.case_id}`)}>
            <td><BandTag band={c.priority_band} score={c.priority_score} /></td>
            <td className="mono">{c.case_id}</td>
            <td>
              <span className="row" style={{ gap: 6 }}>
                <span className="swatch" style={{ background: T[c.transition].color }} />
                {T[c.transition].label}
              </span>
            </td>
            <td className="num">{fmtHa(c.area_ha)}</td>
            {!compact && <td className="num">{c.confidence.toFixed(2)}</td>}
            {!compact && <td>{c.district ?? '—'}</td>}
            <td className="small ink2">{c.observed_t1.slice(0, 4)} → {fmtDate(c.observed_t2)}</td>
            <td><StatusTag status={c.status} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

export default function Cases() {
  const { version } = useApp()
  const [params, setParams] = useSearchParams()
  const [fc, setFc] = useState<CaseFC | null>(null)
  const [aois, setAois] = useState<Aoi[]>([])
  useEffect(() => {
    api.cases().then(setFc)
    api.aois().then(setAois)
  }, [version])

  const f = Object.fromEntries(params.entries())
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(params)
    if (v) n.set(k, v)
    else n.delete(k)
    setParams(n)
  }
  const rows = useMemo(
    () =>
      (fc?.features ?? [])
        .map((x) => x.properties)
        .filter((c) => (!f.status || c.status === f.status) && (!f.band || c.priority_band === f.band) && (!f.aoi || c.aoi_id === f.aoi) && (!f.transition || c.transition === f.transition))
        .sort((a, b) => b.priority_score - a.priority_score),
    [fc, f.status, f.band, f.aoi, f.transition],
  )
  if (!fc) return <Loading what="Loading cases" />
  return (
    <Panel
      title={`${rows.length} case${rows.length === 1 ? '' : 's'}`}
      sub={`${rows.reduce((a, c) => a + c.area_ha, 0).toFixed(1)} ha · sorted by deterministic priority`}
      pad={false}
      right={
        <>
          <select value={f.status ?? ''} onChange={(e) => set('status', e.target.value)} aria-label="Status filter">
            <option value="">All statuses</option>
            {Object.entries(STATUS).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          <select value={f.band ?? ''} onChange={(e) => set('band', e.target.value)} aria-label="Priority filter">
            <option value="">All priorities</option>
            <option value="P1">P1</option><option value="P2">P2</option><option value="P3">P3</option>
          </select>
          <select value={f.transition ?? ''} onChange={(e) => set('transition', e.target.value)} aria-label="Change type filter">
            <option value="">All change types</option>
            {TRANSITIONS.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
          </select>
          <select value={f.aoi ?? ''} onChange={(e) => set('aoi', e.target.value)} aria-label="Area filter">
            <option value="">All areas</option>
            {aois.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
          <a className="btn sm" href="/api/export/cases.csv">CSV</a>
          <a className="btn sm" href="/api/export/cases.geojson">GeoJSON</a>
        </>
      }
    >
      <div style={{ maxHeight: 'calc(100vh - 170px)', overflow: 'auto' }}>
        <CaseTable rows={rows} />
      </div>
    </Panel>
  )
}
