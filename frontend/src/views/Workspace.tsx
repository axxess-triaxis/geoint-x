import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../app-context'
import { BarList } from '../components/Charts'
import MapView from '../components/MapView'
import { BandTag, StatusTag } from '../components/ui'
import { T, TRANSITIONS, fmtDate, fmtHa, fmtPct } from '../theme'
import { aoiBoxes, unionBbox } from '../geo'
import type { Aoi, AoiDetail, CaseFC, Run, Transition } from '../types'

export function LayerPanel({
  visible,
  setVisible,
  counts,
  extra,
}: {
  visible: Set<Transition>
  setVisible: (s: Set<Transition>) => void
  counts: Record<string, number>
  extra?: React.ReactNode
}) {
  return (
    <div className="map-overlay legend" style={{ left: 12, bottom: 28, padding: '8px 10px', width: 236 }}>
      <div className="row" style={{ marginBottom: 4 }}>
        <b className="small">Detected change (heuristic v1)</b>
      </div>
      {TRANSITIONS.map((t) => (
        <button
          key={t.id}
          className={`item${visible.has(t.id) ? '' : ' off'}`}
          onClick={() => {
            const n = new Set(visible)
            if (n.has(t.id)) n.delete(t.id)
            else n.add(t.id)
            setVisible(n)
          }}
          aria-pressed={visible.has(t.id)}
        >
          <span className="swatch" style={{ background: t.color }} />
          <span>{t.short}</span>
          <span className="right muted num">{counts[t.id] ?? 0}</span>
        </button>
      ))}
      {extra}
    </div>
  )
}

export default function Workspace() {
  const { version, bump } = useApp()
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const [aois, setAois] = useState<Aoi[]>([])
  const [districts, setDistricts] = useState<GeoJSON.FeatureCollection | null>(null)
  const aoiId = params.get('aoi') ?? ''
  const [loadedDetail, setDetail] = useState<AoiDetail | null>(null)
  const [corners, setCorners] = useState<[number, number][] | null>(null)
  const [loadedCases, setCases] = useState<CaseFC | null>(null)
  const [viewScene, setViewScene] = useState<string | null>(null)
  const [t1, setT1] = useState('')
  const [t2, setT2] = useState('')
  const [runId, setRunId] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [visible, setVisible] = useState<Set<Transition>>(new Set(TRANSITIONS.map((t) => t.id)))
  const [showMask, setShowMask] = useState(false)
  const [heat, setHeat] = useState(false)
  const [opacity, setOpacity] = useState(1)
  const [sel, setSel] = useState<string | null>(null)
  const [runFc, setRunFc] = useState<(Run & { findings: GeoJSON.FeatureCollection }) | null>(null)

  useEffect(() => {
    api.aois().then(setAois)
    api.districts().then(setDistricts)
  }, [version])

  useEffect(() => {
    if (!aoiId) return
    api.aoi(aoiId).then((d) => {
      setDetail(d)
      const sc = [...d.scenes].sort((a, b) => a.datetime.localeCompare(b.datetime))
      setT1((v) => (sc.some((s) => s.scene_id === v) ? v : sc[0]?.scene_id ?? ''))
      setT2((v) => (sc.some((s) => s.scene_id === v) ? v : sc[Math.max(0, sc.length - 2)]?.scene_id ?? ''))
      setViewScene((v) => (sc.some((s) => s.scene_id === v) ? v : sc[sc.length - 1]?.scene_id ?? null))
      setRunId((r) => (r && d.runs.some((x) => x.id === r) ? r : d.runs[0]?.id ?? null))
    })
    api.corners(aoiId).then(setCorners)
    api.cases({ aoi_id: aoiId }).then(setCases)
  }, [aoiId, version])

  useEffect(() => {
    if (runId) api.run(runId).then(setRunFc)
  }, [runId, version])

  // Derived so a cleared selection never shows the previous area's data.
  const detail = loadedDetail && loadedDetail.id === aoiId ? loadedDetail : null
  const cases = aoiId ? loadedCases : null
  const run: Run | undefined = detail?.runs.find((r) => r.id === runId)
  // All detected regions of the selected analysis (cases and recorded-only findings).
  const runCases = useMemo<CaseFC | null>(() => {
    if (runFc && runFc.id === runId) {
      const feats = [...(runFc.findings as CaseFC).features].sort(
        (a, b) => (b.properties.priority_score ?? 0) - (a.properties.priority_score ?? 0),
      )
      return { type: 'FeatureCollection', features: feats }
    }
    return runId ? null : cases
  }, [runFc, runId, cases])

  const selCase = sel
    ? runCases?.features.find((f) => f.properties.finding_id === sel || f.properties.case_id === sel)?.properties.linked_case_id ??
      (sel.startsWith('CASE-') ? sel : null)
    : null
  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const f of runCases?.features ?? []) c[f.properties.transition] = (c[f.properties.transition] ?? 0) + 1
    return c
  }, [runCases])

  const areaByClass = useMemo(() => {
    const a: Record<string, number> = {}
    for (const f of runCases?.features ?? []) a[f.properties.transition] = (a[f.properties.transition] ?? 0) + f.properties.area_ha
    return TRANSITIONS.filter((t) => a[t.id]).map((t) => ({ key: t.id, label: t.short, value: a[t.id], color: t.color }))
  }, [runCases])

  const scenes = useMemo(() => [...(detail?.scenes ?? [])].sort((a, b) => a.datetime.localeCompare(b.datetime)), [detail])
  const maskUrl = run?.artifacts.find((a) => a.kind === 'change_mask')?.uri

  const doRun = async () => {
    if (!aoiId) return
    setBusy(true)
    setErr(null)
    try {
      const r = await api.runDetection(aoiId, t1, t2)
      setRunId(r.run.id)
      bump()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const fitTo = detail ? detail.bbox : aois.length ? unionBbox(aois) : null

  return (
    <div className="workspace">
      <aside className="side">
        <section>
          <h3>Monitored area</h3>
          <div className="stack" style={{ marginTop: 8 }}>
            {aois.map((a) => (
              <button
                key={a.id}
                className="btn"
                style={{ justifyContent: 'flex-start', textAlign: 'left', background: a.id === aoiId ? 'var(--accent-soft)' : undefined, borderColor: a.id === aoiId ? 'var(--accent)' : undefined }}
                onClick={() => setParams({ aoi: a.id })}
              >
                <span style={{ flex: 1 }}>
                  <b>{a.name}</b>
                  <br />
                  <span className="muted small">
                    {a.mode === 'encroachment' ? 'Wetland encroachment' : 'Land use / land cover'} · {a.district ?? '—'} · {a.scene_count} observations
                  </span>
                </span>
                {a.p1_open > 0 && <BandTag band="P1" />}
              </button>
            ))}
          </div>
        </section>

        {detail && (
          <>
            <section>
              <p className="small ink2" style={{ margin: 0 }}>{detail.description}</p>
              <p className="small muted" style={{ margin: '6px 0 0' }}>
                Sentinel-2 catalogue: {detail.catalog_stats.acquisitions} acquisitions since {fmtDate(detail.catalog_stats.first)}, {detail.catalog_stats.clear_le_20pct} with ≤20% cloud.
                Demo pack holds the clearest mid-January scene of each dry season.
              </p>
            </section>
            <section>
              <div className="row">
                <h3>Observations</h3>
                <span className="right small muted">click to view on map</span>
              </div>
              <div className="timeline" style={{ marginTop: 8 }}>
                {scenes.map((s) => (
                  <button
                    key={s.scene_id}
                    className={[viewScene === s.scene_id ? 'on' : '', s.scene_id === t1 ? 't1' : '', s.scene_id === t2 ? 't2' : ''].join(' ')}
                    onClick={() => setViewScene(s.scene_id)}
                    title={`${s.scene_id}\n${fmtDate(s.datetime)} · AOI clear ${fmtPct(s.aoi_valid_fraction, 1)}`}
                  >
                    {new Date(s.datetime).toLocaleDateString('en-GB', { month: 'short' })} ’{s.datetime.slice(2, 4)}
                  </button>
                ))}
              </div>
              <p className="small muted" style={{ margin: '6px 0 0' }}>
                Showing {viewScene ? fmtDate(scenes.find((s) => s.scene_id === viewScene)?.datetime) : '—'} true colour ·{' '}
                <span style={{ color: '#2a78d6' }}>■</span> before · <span style={{ color: '#eb6834' }}>■</span> after
              </p>
              <label className="field" style={{ marginTop: 8 }}>
                Imagery opacity
                <input type="range" min={0} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(Number(e.target.value))} />
              </label>
            </section>
            <section>
              <h3>Run change detection</h3>
              <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 8, marginTop: 8 }}>
                <label className="field">
                  Before (T1)
                  <select value={t1} onChange={(e) => setT1(e.target.value)}>
                    {scenes.map((s) => (
                      <option key={s.scene_id} value={s.scene_id}>{fmtDate(s.datetime)}</option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  After (T2)
                  <select value={t2} onChange={(e) => setT2(e.target.value)}>
                    {scenes.map((s) => (
                      <option key={s.scene_id} value={s.scene_id}>{fmtDate(s.datetime)}</option>
                    ))}
                  </select>
                </label>
              </div>
              <button className="btn primary" style={{ marginTop: 10, width: '100%', justifyContent: 'center' }} disabled={busy || !t1 || !t2} onClick={doRun}>
                {busy ? 'Analysing observations…' : 'Detect change'}
              </button>
              {err && <p className="error">{err}</p>}
              <p className="small muted" style={{ margin: '6px 0 0' }}>
                Deterministic pipeline: cloud mask (SCL) → NDVI/MNDWI/NDBI → rule-based transitions → regions ≥0.5 ha → confidence, boundary overlap, priority. Later observations are used to test persistence.
              </p>
            </section>
            {detail.runs.length > 0 && (
              <section>
                <div className="row">
                  <h3>Analyses</h3>
                  <select className="right" value={runId ?? ''} onChange={(e) => setRunId(e.target.value || null)} aria-label="Analysis run">
                    {detail.runs.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.id} · {r.t1_datetime.slice(0, 4)}→{r.t2_datetime.slice(0, 4)} · {r.triggered_by}
                      </option>
                    ))}
                  </select>
                </div>
                {run && (
                  <div className="stack" style={{ marginTop: 8 }}>
                    <div className="small ink2">
                      {fmtDate(run.t1_datetime)} → {fmtDate(run.t2_datetime)} · {run.finding_count} regions · {run.case_count} cases · {fmtPct(run.stats.valid_fraction, 1)} of area clear in both
                    </div>
                    <BarList items={areaByClass} unit="ha" />
                    <label className="row small">
                      <input type="checkbox" checked={showMask} onChange={(e) => setShowMask(e.target.checked)} /> Show per-pixel change map (before minimum-area filter)
                    </label>
                  </div>
                )}
              </section>
            )}
            {runCases && runCases.features.length > 0 && (
              <section style={{ padding: 0 }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Case</th>
                      <th>Change</th>
                      <th className="num">ha</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runCases.features.slice(0, 60).map((f) => (
                      <tr
                        key={f.properties.finding_id}
                        className={`click${sel === f.properties.finding_id ? ' sel' : ''}`}
                        onClick={() => setSel(f.properties.finding_id)}
                        onDoubleClick={() => f.properties.linked_case_id && nav(`/cases/${f.properties.linked_case_id}`)}
                      >
                        <td>
                          {f.properties.priority_band && <BandTag band={f.properties.priority_band} />}
                          <div className="mono muted">{f.properties.linked_case_id ?? f.properties.finding_id.replace(/^RUN-\d+-/, '')}</div>
                        </td>
                        <td>
                          <span className="row" style={{ gap: 5 }}>
                            <span className="swatch" style={{ background: T[f.properties.transition].color }} />
                            {T[f.properties.transition].short}
                          </span>
                        </td>
                        <td className="num">{fmtHa(f.properties.area_ha)}</td>
                        <td title={f.properties.triage ?? ''}><StatusTag status={f.properties.status} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {selCase && (
                  <div style={{ padding: 10 }}>
                    <button className="btn primary" onClick={() => nav(`/cases/${selCase}`)}>Open investigation {selCase}</button>
                  </div>
                )}
              </section>
            )}
          </>
        )}
        {!detail && (
          <section>
            <p className="ink2 small" style={{ margin: 0 }}>
              Select a monitored area to browse its satellite observations and run change detection. The same engine
              serves land-use change monitoring and wetland / government-land encroachment monitoring.
            </p>
          </section>
        )}
      </aside>
      <div style={{ position: 'relative' }}>
        <MapView
          districts={districts}
          aoiBoxes={aoiBoxes(aois)}
          boundaries={detail?.polygons ?? null}
          cases={runCases}
          visibleTransitions={visible}
          imagery={detail && corners && viewScene ? { url: api.sceneUrl(detail.id, viewScene), corners, opacity } : null}
          changeMask={showMask && maskUrl && run ? { url: maskUrl, corners: run.overlay_corners } : null}
          fitTo={fitTo}
          selectedCaseId={sel}
          heatmap={heat}
          onCaseClick={(id) => setSel(id)}
          onAoiClick={(id) => setParams({ aoi: id })}
        />
        {detail && (
          <LayerPanel
            visible={visible}
            setVisible={setVisible}
            counts={counts}
            extra={
              <label className="row small" style={{ marginTop: 6 }}>
                <input type="checkbox" checked={heat} onChange={(e) => setHeat(e.target.checked)} /> Priority heatmap
              </label>
            }
          />
        )}
      </div>
    </div>
  )
}

