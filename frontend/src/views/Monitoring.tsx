import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../app-context'
import MapView from '../components/MapView'
import { BandTag, StatusTag } from '../components/ui'
import { POLYGON_KIND, T, TRANSITIONS, fmtHa } from '../theme'
import type { Aoi, AoiDetail, BoundaryStat, CaseFC, Transition } from '../types'
import { aoiBoxes } from '../geo'
import { LayerPanel } from './Workspace'

export default function Monitoring() {
  const { version, bump } = useApp()
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const [aois, setAois] = useState<Aoi[]>([])
  const [detail, setDetail] = useState<AoiDetail | null>(null)
  const [corners, setCorners] = useState<[number, number][] | null>(null)
  const [cases, setCases] = useState<CaseFC | null>(null)
  const [stats, setStats] = useState<BoundaryStat[]>([])
  const [visible, setVisible] = useState<Set<Transition>>(new Set(TRANSITIONS.map((t) => t.id)))
  const [sel, setSel] = useState<string | null>(null)
  const [scope, setScope] = useState<'boundary' | 'all'>('boundary')

  const encAois = aois.filter((a) => a.mode === 'encroachment')
  const aoiId = params.get('aoi') ?? encAois[0]?.id ?? ''

  useEffect(() => {
    api.aois().then(setAois)
    api.boundaries().then((b) => setStats(b.monitored_boundaries))
  }, [version])
  useEffect(() => {
    if (!aoiId) return
    api.aoi(aoiId).then(setDetail)
    api.corners(aoiId).then(setCorners)
    api.cases({ aoi_id: aoiId }).then(setCases)
  }, [aoiId, version])

  const aoiStats = stats.filter((s) => s.aoi_id === aoiId)
  const related = useMemo(() => new Set(aoiStats.flatMap((s) => s.case_ids)), [aoiStats])
  const shown: CaseFC | null = useMemo(() => {
    if (!cases) return null
    if (scope === 'all') return cases
    return { ...cases, features: cases.features.filter((f) => related.has(f.properties.case_id)) }
  }, [cases, related, scope])
  const queue = (shown?.features ?? [])
    .map((f) => f.properties)
    .filter((c) => c.status === 'UNVERIFIED' || c.status === 'UNDER_REVIEW')
    .sort((a, b) => b.priority_score - a.priority_score)
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const f of shown?.features ?? []) c[f.properties.transition] = (c[f.properties.transition] ?? 0) + 1
    return c
  }, [shown])
  const latestScene = detail?.scenes.map((s) => s.scene_id).sort().pop()

  return (
    <div className="workspace">
      <aside className="side">
        <section>
          <div className="row">
            <h3>Monitored area</h3>
            <select className="right" value={aoiId} onChange={(e) => setParams({ aoi: e.target.value })} aria-label="Area">
              {aois.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>
          {detail && !detail.runs.length && (
            <p className="small banner" style={{ marginTop: 8 }}>
              This area has not been analysed yet. Run change detection from the <a href={`/map?aoi=${aoiId}`}>change detection</a> view
              or let the monitoring agent schedule it.
            </p>
          )}
        </section>
        <section style={{ padding: 0 }}>
          <div className="row" style={{ padding: '10px 14px 6px' }}>
            <h3>Monitored boundaries</h3>
          </div>
          <table className="data">
            <thead>
              <tr><th>Boundary</th><th className="num">Inside</th><th className="num">Buffer</th><th className="num">Open</th></tr>
            </thead>
            <tbody>
              {aoiStats.map((s) => (
                <tr key={s.polygon_id}>
                  <td>
                    <span className="row" style={{ gap: 6 }}>
                      <span className="swatch" style={{ background: POLYGON_KIND[s.kind]?.color ?? '#52514e' }} />
                      <b>{s.polygon}</b>
                    </span>
                    <div className="small muted">
                      {POLYGON_KIND[s.kind]?.label ?? s.kind} · {s.official_boundary ? 'official record' : 'not an official record'}
                    </div>
                    <div className="small muted">{s.boundary_source}</div>
                  </td>
                  <td className="num">{fmtHa(s.changed_area_inside_ha)} ha</td>
                  <td className="num">{fmtHa(s.changed_area_in_buffer_ha)} ha</td>
                  <td className="num">{s.open_case_ids.length}</td>
                </tr>
              ))}
              {!aoiStats.length && (
                <tr><td colSpan={4} className="muted">No boundaries registered for this area.</td></tr>
              )}
            </tbody>
          </table>
          <p className="small muted" style={{ margin: 0, padding: '6px 14px 10px' }}>
            Buffer = regions within 200 m outside the boundary. Areas are summed over all analyses.
          </p>
        </section>
        <ImportBoundary aoiId={aoiId} onDone={bump} />
        <section style={{ padding: 0 }}>
          <div className="row" style={{ padding: '10px 14px 6px' }}>
            <h3>Verification queue</h3>
            <span className="right row small">
              <label className="row"><input type="radio" checked={scope === 'boundary'} onChange={() => setScope('boundary')} /> boundary-related</label>
              <label className="row"><input type="radio" checked={scope === 'all'} onChange={() => setScope('all')} /> all</label>
            </span>
          </div>
          <table className="data">
            <tbody>
              {queue.slice(0, 30).map((c) => (
                <tr key={c.case_id} className={`click${sel === c.case_id ? ' sel' : ''}`} onClick={() => setSel(c.case_id)} onDoubleClick={() => nav(`/cases/${c.case_id}`)}>
                  <td><BandTag band={c.priority_band} score={c.priority_score} /></td>
                  <td>
                    <span className="row" style={{ gap: 5 }}><span className="swatch" style={{ background: T[c.transition].color }} />{T[c.transition].short}</span>
                    <div className="mono muted">{c.case_id}</div>
                  </td>
                  <td className="num">{fmtHa(c.area_ha)} ha</td>
                  <td><StatusTag status={c.status} /></td>
                </tr>
              ))}
              {!queue.length && <tr><td className="muted">No open cases.</td></tr>}
            </tbody>
          </table>
          {sel && (
            <div style={{ padding: 10 }}>
              <button className="btn primary" onClick={() => nav(`/cases/${sel}`)}>Open investigation {sel}</button>
            </div>
          )}
        </section>
      </aside>
      <div style={{ position: 'relative' }}>
        <MapView
          aoiBoxes={aoiBoxes(aois.filter((a) => a.id === aoiId))}
          boundaries={detail?.polygons ?? null}
          cases={shown}
          visibleTransitions={visible}
          imagery={detail && corners && latestScene ? { url: api.sceneUrl(detail.id, latestScene), corners, opacity: 0.85 } : null}
          fitTo={detail?.bbox ?? null}
          selectedCaseId={sel}
          showDistricts={false}
          onCaseClick={setSel}
        />
        <LayerPanel
          visible={visible}
          setVisible={setVisible}
          counts={counts}
          extra={
            <div className="small" style={{ marginTop: 6, borderTop: '1px solid var(--border)', paddingTop: 6 }}>
              <div className="item"><span className="swatch" style={{ background: 'transparent', border: '2px solid #2a78d6' }} />Wetland outline</div>
              <div className="item"><span className="swatch" style={{ background: 'transparent', border: '2px solid #1c5cab' }} />Protected area</div>
              <div className="item"><span className="swatch" style={{ background: 'transparent', border: '2px solid #0b0b0b' }} />Government land</div>
              <div className="item"><span className="swatch" style={{ background: 'transparent', border: '1px dashed #52514e' }} />200 m watch buffer</div>
            </div>
          }
        />
      </div>
    </div>
  )
}

function ImportBoundary({ aoiId, onDone }: { aoiId: string; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [kind, setKind] = useState('government_land')
  const [official, setOfficial] = useState(false)
  const [geo, setGeo] = useState<unknown>(null)
  const [msg, setMsg] = useState<string | null>(null)
  if (!open)
    return (
      <section>
        <button className="btn" onClick={() => setOpen(true)}>Import boundary (GeoJSON)</button>
        <p className="small muted" style={{ margin: '6px 0 0' }}>Register a government land parcel, wetland or protected area. It is used in the next analysis of this area.</p>
      </section>
    )
  return (
    <section className="stack">
      <h3>Import boundary</h3>
      <label className="field">Name<input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Govt. land, Dag No. 123" /></label>
      <label className="field">Kind
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="government_land">Government land</option>
          <option value="wetland">Wetland</option>
          <option value="protected_area">Protected area</option>
          <option value="water_body">Water body</option>
        </select>
      </label>
      <label className="field">GeoJSON file (EPSG:4326 Polygon / MultiPolygon)
        <input type="file" accept=".geojson,.json" onChange={async (e) => {
          const f = e.target.files?.[0]
          if (!f) return
          try { setGeo(JSON.parse(await f.text())); setMsg(null) } catch { setMsg('Not valid JSON') }
        }} />
      </label>
      <label className="row small"><input type="checkbox" checked={official} onChange={(e) => setOfficial(e.target.checked)} /> This is an official record (I have the source document)</label>
      <div className="row">
        <button className="btn primary" disabled={!name || !geo} onClick={async () => {
          try {
            await api.importPolygon(aoiId, { name, kind, geometry: geo, source: 'User import (dashboard)', official })
            setMsg('Boundary registered. Re-run detection to evaluate it.')
            setOpen(false)
            onDone()
          } catch (e) { setMsg((e as Error).message) }
        }}>Register</button>
        <button className="btn" onClick={() => setOpen(false)}>Cancel</button>
      </div>
      {msg && <p className="small">{msg}</p>}
    </section>
  )
}
