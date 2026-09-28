import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../app-context'
import MapView from '../components/MapView'
import { Kpi, Loading, Panel } from '../components/ui'
import { fmtDate, fmtPct, humanize } from '../theme'
import type { Analytics, Aoi, CaseEvent, CaseFC } from '../types'
import { CaseTable } from './Cases'
import { aoiBoxes, unionBbox } from '../geo'

export default function Overview() {
  const { version } = useApp()
  const nav = useNavigate()
  const [aois, setAois] = useState<Aoi[]>([])
  const [cases, setCases] = useState<CaseFC | null>(null)
  const [a, setA] = useState<Analytics | null>(null)
  const [events, setEvents] = useState<CaseEvent[]>([])
  const [districts, setDistricts] = useState<GeoJSON.FeatureCollection | null>(null)

  useEffect(() => {
    api.aois().then(setAois)
    api.cases().then(setCases)
    api.analytics().then(setA)
    api.activity().then(setEvents)
    api.districts().then(setDistricts)
  }, [version])

  if (!a) return <Loading what="Loading overview" />
  const t = a.totals
  const queue = (cases?.features ?? [])
    .map((f) => f.properties)
    .filter((c) => c.status === 'UNVERIFIED' || c.status === 'UNDER_REVIEW')
    .sort((x, y) => y.priority_score - x.priority_score)
    .slice(0, 8)

  return (
    <div className="grid">
      <section className="panel kpis">
        <Kpi label="Monitored areas" value={t.monitored_areas} sub={`${a.coverage.reduce((s, c) => s + c.area_km2, 0).toFixed(0)} km² under watch`} />
        <Kpi label="Detected change regions" value={t.regions} sub={`${t.changed_area_ha.toFixed(0)} ha across ${t.analyses} analyses`} />
        <Kpi label="Open cases" value={t.open} sub={`${t.p1_open} at P1 · ${t.regions - t.cases} recorded without a case`} />
        <Kpi label="Confirmed" value={t.confirmed} sub="by a reviewer" />
        <Kpi label="Rejected" value={t.rejected} sub={t.rejection_rate == null ? 'no decisions yet' : `${fmtPct(t.rejection_rate)} of decided`} />
        <Kpi label="Latest observation" value={latest(a)} sub="Sentinel-2 L2A, demo pack" />
      </section>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1.4fr) minmax(0, 1fr)' }}>
        <Panel title="Monitored areas, Assam" sub="click an area to open it" pad={false}>
          <div style={{ height: 430 }}>
            <MapView
              districts={districts}
              aoiBoxes={aoiBoxes(aois)}
              cases={cases}
              fitTo={aois.length ? padBbox(unionBbox(aois)) : null}
              onCaseClick={(id) => nav(`/cases/${id}`)}
              onAoiClick={(id) => nav(`/map?aoi=${id}`)}
            />
          </div>
        </Panel>
        <Panel title="Areas" pad={false}>
          <table className="data">
            <thead>
              <tr><th>Area</th><th>Mode</th><th className="num">Open</th><th className="num">P1</th><th>Last observed</th></tr>
            </thead>
            <tbody>
              {aois.map((x) => (
                <tr key={x.id} className="click" onClick={() => nav(x.mode === 'encroachment' ? `/monitoring?aoi=${x.id}` : `/map?aoi=${x.id}`)}>
                  <td><b>{x.name}</b><div className="small muted">{x.district}</div></td>
                  <td className="small">{x.mode === 'encroachment' ? 'Encroachment (D-17)' : 'LULC change (D-21)'}</td>
                  <td className="num">{x.open_cases}</td>
                  <td className="num">{x.p1_open}</td>
                  <td className="small">{x.last_observed_at ? fmtDate(x.last_observed_at) : <span className="muted">not analysed</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="body">
            <h3>Recent activity</h3>
            <ul className="events" style={{ marginTop: 8 }}>
              {events.slice(0, 7).map((e) => (
                <li key={e.id}>
                  <span className="pip" />
                  <div className="small">
                    <Link to={`/cases/${e.case_id}`} className="mono">{e.case_id}</Link> {humanize(e.action)}
                    {e.to_status && e.from_status !== e.to_status ? ` → ${humanize(e.to_status).toLowerCase()}` : ''}
                    <div className="muted">{e.actor} · {new Date(e.ts).toLocaleString('en-GB')}</div>
                  </div>
                </li>
              ))}
            </ul>
            {!events.length && <p className="muted small" style={{ margin: 0 }}>No activity yet. Run change detection on an area to begin.</p>}
          </div>
        </Panel>
      </div>

      <Panel title="Priority queue" sub="open cases, highest deterministic priority first" right={<Link to="/cases?status=UNVERIFIED">All cases →</Link>} pad={false}>
        <CaseTable rows={queue} />
      </Panel>
    </div>
  )
}

function latest(a: Analytics) {
  const dates = Object.values(a.land_composition).flatMap((xs) => xs.map((x) => x.date))
  if (!dates.length) return '—'
  return fmtDate(dates.sort().pop())
}

function padBbox([a, b, c, d]: [number, number, number, number]): [number, number, number, number] {
  return [a - 0.3, b - 0.3, c + 0.3, d + 0.3]
}
