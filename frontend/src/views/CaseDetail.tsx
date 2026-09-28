import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../app-context'
import MapView from '../components/MapView'
import { BandTag, Compare, Loading, Panel, StatusTag, TransitionTag } from '../components/ui'
import { BAND, fmtDate, fmtHa, fmtPct, humanize } from '../theme'
import type { AoiDetail, CaseDetail as CD, CaseFC, Interpretation } from '../types'

const ACTION_LABEL: Record<string, string> = {
  assign: 'Assign',
  start_review: 'Start review',
  confirm: 'Confirm change',
  reject: 'Reject',
  reopen: 'Reopen',
  add_note: 'Add note',
}

export default function CaseDetail() {
  const { id = '' } = useParams()
  const { version, bump, role } = useApp()
  const [d, setD] = useState<CD | null>(null)
  const [aoi, setAoi] = useState<AoiDetail | null>(null)
  const [corners, setCorners] = useState<[number, number][] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [interp, setInterp] = useState<Interpretation | null>(null)
  const [interpMeta, setInterpMeta] = useState<Record<string, unknown> | null>(null)
  const [aiBusy, setAiBusy] = useState(false)

  useEffect(() => {
    api
      .caseDetail(id)
      .then((x) => {
        setErr(null)
        setD(x)
        setInterp(x.case.interpretation)
        setInterpMeta((x.case.interpretation?.meta as Record<string, unknown>) ?? null)
        api.aoi(x.case.aoi_id).then(setAoi)
        api.corners(x.case.aoi_id).then(setCorners)
      })
      .catch((e) => setErr((e as Error).message))
  }, [id, version, role])

  if (err) return <p className="error">{err}</p>
  if (!d) return <Loading what="Loading case" />
  const { case: c, finding: f } = d
  const crop = (stem: string) => f.evidence.find((e) => e.id === `${f.id}:${stem}`)?.uri ?? ''
  const fc: CaseFC = {
    type: 'FeatureCollection',
    features: [
      {
        type: 'Feature',
        id: c.id,
        geometry: f.geometry,
        properties: {
          case_id: c.id, finding_id: f.id, aoi_id: c.aoi_id, status: c.status, priority_band: c.priority_band,
          priority_score: c.priority_score, transition: c.transition, transition_label: f.transition_label,
          area_ha: c.area_ha, confidence: c.confidence, district: c.district,
          observed_t1: f.t1.datetime.slice(0, 10), observed_t2: f.t2.datetime.slice(0, 10), centroid: f.centroid,
        },
      },
    ],
  }
  const [lon, lat] = f.centroid
  const pad = 0.012
  const factors = [...c.priority.factors].sort((a, b) => (b.contribution ?? 0) - (a.contribution ?? 0))

  const genAi = async () => {
    setAiBusy(true)
    try {
      const r = await api.interpret(c.id)
      setInterp(r.interpretation)
      setInterpMeta(r.meta)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setAiBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1.55fr) minmax(320px, 1fr)', alignItems: 'start' }}>
      <div className="grid">
        <Panel pad={false}>
          <div style={{ padding: '12px 14px' }} className="stack">
            <div className="row wrap" style={{ gap: 10 }}>
              <Link to="/cases" className="small">← Cases</Link>
              <h1 className="mono" style={{ fontSize: 16 }}>{c.id}</h1>
              <BandTag band={c.priority_band} score={c.priority_score} />
              <StatusTag status={c.status} />
              <span className="right row" style={{ gap: 8 }}>
                <a className="btn sm" href={`/api/cases/${c.id}/report`} target="_blank" rel="noreferrer">Investigation report</a>
              </span>
            </div>
            <div className="row wrap" style={{ gap: 16 }}>
              <b><TransitionTag t={c.transition} /></b>
              <span><b className="num">{fmtHa(f.area_ha)} ha</b> <span className="muted">({f.pixel_count} px at 10 m)</span></span>
              <span title="District per geoBoundaries 2021 (centroid in polygon); not an official determination">{f.district ?? 'District n/a'} <span className="muted small">(geoBoundaries)</span></span>
              <span className="muted">{fmtDate(f.t1.datetime)} → {fmtDate(f.t2.datetime)}</span>
              <span className="muted mono">{lat.toFixed(5)}N {lon.toFixed(5)}E</span>
            </div>
            <div className="banner">
              Suspected change detected from satellite imagery, for verification. This is not a legal determination
              of encroachment{f.overlaps.some((o) => o.fraction_of_finding_inside > 0 || o.within_buffer) ? '; the boundary shown is not an official record unless stated' : ''}.
            </div>
          </div>
        </Panel>

        <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
          <Panel title="Before / after" sub="drag to compare · Sentinel-2 true colour, fixed stretch">
            <Compare before={crop('before')} after={crop('after')} labels={[f.t1.datetime.slice(0, 10), f.t2.datetime.slice(0, 10)]} />
            <div className="thumbs" style={{ marginTop: 8 }}>
              <figure><img src={crop('before')} alt="Before" /><figcaption>T1 {f.t1.scene_id.slice(0, 22)}</figcaption></figure>
              <figure><img src={crop('after')} alt="After" /><figcaption>T2 {f.t2.scene_id.slice(0, 22)}</figcaption></figure>
              <figure><img src={crop('mask')} alt="Detected region" /><figcaption>Detected region</figcaption></figure>
            </div>
          </Panel>
          <Panel title="Location" sub="boundary and detected region" pad={false}>
            <div style={{ height: 380 }}>
              <MapView
                cases={fc}
                boundaries={aoi?.polygons ?? null}
                imagery={corners ? { url: api.sceneUrl(c.aoi_id, f.t2.scene_id), corners } : null}
                fitTo={[lon - pad, lat - pad * 0.8, lon + pad, lat + pad * 0.8]}
                selectedCaseId={c.id}
                showDistricts={false}
              />
            </div>
          </Panel>
        </div>

        <Panel title="Measurements" sub={`${f.algorithm_version} · all figures computed deterministically`}>
          <div className="grid" style={{ gridTemplateColumns: '1fr 1fr', gap: 18 }}>
            <dl className="facts">
              <dt>Affected area</dt><dd className="num">{f.area_ha.toFixed(2)} ha</dd>
              <dt>Confidence</dt><dd className="num">{f.confidence.toFixed(2)} <span className="muted small">heuristic, not a probability</span></dd>
              <dt>Persistence</dt><dd>{f.persistence == null ? <span className="muted">no later observation yet</span> : `${fmtPct(f.persistence)} still changed later`}</dd>
              <dt>Clear sky T1 / T2</dt><dd className="num">{fmtPct(f.t1.aoi_valid_fraction, 1)} / {fmtPct(f.t2.aoi_valid_fraction, 1)}</dd>
              <dt>Baseline (2020)</dt>
              <dd>{Object.entries(f.baseline_landcover).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${k} ${fmtPct(v)}`).join(', ') || '—'}</dd>
            </dl>
            <table className="data">
              <thead><tr><th>Index</th><th className="num">T1</th><th className="num">T2</th><th className="num">Δ</th></tr></thead>
              <tbody>
                {Object.keys(f.index_deltas).map((k) => (
                  <tr key={k}>
                    <td>{k.toUpperCase()}</td>
                    <td className="num">{f.index_means_t1[k]?.toFixed(3)}</td>
                    <td className="num">{f.index_means_t2[k]?.toFixed(3)}</td>
                    <td className="num"><b>{f.index_deltas[k] > 0 ? '+' : ''}{f.index_deltas[k].toFixed(3)}</b></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {f.overlaps.length > 0 && (
            <table className="data" style={{ marginTop: 12 }}>
              <thead><tr><th>Monitored boundary</th><th>Kind</th><th className="num">Inside</th><th className="num">Overlap</th><th>Crosses</th><th className="num">Distance</th></tr></thead>
              <tbody>
                {f.overlaps.map((o) => (
                  <tr key={o.polygon_id}>
                    <td>{o.polygon_name}</td>
                    <td>{humanize(o.polygon_kind)}</td>
                    <td className="num">{fmtPct(o.fraction_of_finding_inside)}</td>
                    <td className="num">{o.overlap_ha.toFixed(2)} ha</td>
                    <td>{o.crosses_boundary ? 'Yes' : 'No'}</td>
                    <td className="num">{o.within_buffer ? `${o.distance_to_boundary_m.toFixed(0)} m outside` : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <h3 style={{ marginTop: 14, marginBottom: 6 }}>Confidence factors</h3>
          <FactorBars factors={f.confidence_factors.map((x) => ({ ...x, contribution: x.value }))} max={1} color="#2a78d6" fmt={(v) => v.toFixed(2)} />
        </Panel>

        <Panel title="Evidence register" sub="every artifact is hashed; AI may cite only these ids">
          <table className="data">
            <thead><tr><th>Id</th><th>Kind</th><th>Description</th><th>SHA-256</th></tr></thead>
            <tbody>
              {f.evidence.map((e) => (
                <tr key={e.id}>
                  <td className="mono">{e.uri ? <a href={e.uri} target="_blank" rel="noreferrer">{e.id}</a> : e.id}</td>
                  <td>{humanize(e.kind)}</td>
                  <td className="small">{e.description}</td>
                  <td className="mono muted">{e.sha256?.slice(0, 12) ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="small ink2" style={{ margin: '10px 0 0', paddingLeft: 18 }}>
            {f.caveats.map((x) => <li key={x}>{x}</li>)}
          </ul>
        </Panel>
      </div>

      <div className="grid">
        <Workflow d={d} onDone={bump} />

        <Panel title="Why this priority" sub={c.priority.engine_version} right={<BandTag band={c.priority_band} score={c.priority_score} />}>
          <FactorBars factors={factors} max={30} color={BAND[c.priority_band].color} fmt={(v) => `+${v.toFixed(1)}`} />
          <p className="small muted" style={{ margin: '8px 0 0' }}>Points = factor value × weight × 100. Bands: P1 ≥ 70, P2 ≥ 45.</p>
        </Panel>

        <Panel
          title="AI interpretation"
          sub={interp ? (interp.source === 'gemini' ? `Gemini (${interp.model})` : 'deterministic template') : undefined}
          right={<button className="btn sm" onClick={genAi} disabled={aiBusy}>{aiBusy ? 'Generating…' : interp ? 'Regenerate' : 'Generate'}</button>}
        >
          {!interp && <p className="muted small" style={{ margin: 0 }}>Generates a plain-language brief from the recorded finding. The model receives only the structured finding and evidence ids; outputs citing unknown evidence, quoting unsupported figures or using accusatory language are discarded.</p>}
          {interp && (
            <div className="stack">
              <p style={{ margin: 0 }}>{interp.summary}</p>
              <div>
                <h3>Plausible explanations</h3>
                <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{interp.plausible_explanations.map((x) => <li key={x}>{x}</li>)}</ul>
              </div>
              <div>
                <h3>Verification steps</h3>
                <ol style={{ margin: '4px 0 0', paddingLeft: 18 }}>{interp.verification_steps.map((x) => <li key={x}>{x}</li>)}</ol>
              </div>
              <div className="small muted">
                Cites: {interp.evidence_refs.map((r) => <code key={r} style={{ marginRight: 6 }}>{r.replace(f.id + ':', '')}</code>)}
              </div>
              {interpMeta?.problems ? (
                <div className="small banner">Model output was rejected by guards ({(interpMeta.problems as string[]).join('; ')}); template shown.</div>
              ) : interpMeta?.reason ? (
                <div className="small muted">Template used: {String(interpMeta.reason)}</div>
              ) : null}
            </div>
          )}
        </Panel>

        <Panel title="Audit trail" right={<span className={`status ${d.audit_chain.ok ? 'good' : 'neutral'}`}>{d.audit_chain.ok ? `Hash chain intact · ${d.audit_chain.checked} events` : `Chain broken: ${d.audit_chain.reason}`}</span>}>
          <ul className="events">
            {d.events.map((e) => (
              <li key={e.id}>
                <span className="pip" style={{ background: e.action === 'confirm' ? '#0ca30c' : e.action === 'reject' ? '#898781' : e.action === 'created' ? '#2a78d6' : undefined }} />
                <div>
                  <div><b>{humanize(e.action)}</b> {e.to_status && e.from_status !== e.to_status && <span className="muted">→ {humanize(e.to_status).toLowerCase()}</span>}</div>
                  <div className="small muted">{new Date(e.ts).toLocaleString('en-GB')} · {e.actor} ({e.role})</div>
                  {typeof e.payload.note === 'string' && <div className="small">“{e.payload.note}”</div>}
                  {typeof e.payload.reject_reason === 'string' && <div className="small">Reason: {humanize(e.payload.reject_reason)}</div>}
                  {typeof e.payload.file === 'string' && (
                    <div className="small"><a href={String(e.payload.uri)} target="_blank" rel="noreferrer">{e.payload.file}</a> <span className="mono muted">{String(e.payload.sha256).slice(0, 12)}</span></div>
                  )}
                  <div className="mono muted" style={{ fontSize: 10.5 }}>#{e.seq} {e.hash.slice(0, 16)}</div>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
    </div>
  )
}

function FactorBars({ factors, max, color, fmt }: { factors: { name: string; value: number; contribution?: number; explanation: string }[]; max: number; color: string; fmt: (v: number) => string }) {
  return (
    <div className="barlist">
      {factors.map((x) => (
        <div key={x.name} title={x.explanation}>
          <div className="r">
            <span className="lab">{humanize(x.name)}</span>
            <span className="track"><span className="fill" style={{ display: 'block', width: `${Math.min(100, ((x.contribution ?? 0) / max) * 100)}%`, background: color }} /></span>
            <span className="num small" style={{ textAlign: 'right' }}>{fmt(x.contribution ?? 0)}</span>
          </div>
          <div className="small muted" style={{ marginLeft: 0, marginTop: 1 }}>{x.explanation}</div>
        </div>
      ))}
    </div>
  )
}

function Workflow({ d, onDone }: { d: CD; onDone: () => void }) {
  const { role, user } = useApp()
  const [note, setNote] = useState('')
  const [reason, setReason] = useState('')
  const [assignee, setAssignee] = useState('r.das')
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const c = d.case

  const act = async (action: string) => {
    setBusy(true)
    setErr(null)
    try {
      await api.action(c.id, { action, note: note || undefined, reject_reason: action === 'reject' ? reason : undefined, assignee: action === 'assign' ? assignee : undefined })
      setNote('')
      onDone()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const upload = async () => {
    if (!file) return
    setBusy(true)
    setErr(null)
    try {
      await api.attach(c.id, file, note, 'field_note')
      setFile(null)
      setNote('')
      onDone()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  const acts = d.allowed_actions.filter((a) => a !== 'attach' && a !== 'add_note')
  return (
    <Panel title="Verification" sub={`acting as ${user} · ${role}`}>
      <div className="stack">
        <dl className="facts small">
          <dt>Status</dt><dd><StatusTag status={c.status} /></dd>
          <dt>Assignee</dt><dd>{c.assignee ?? <span className="muted">unassigned</span>}</dd>
          {c.reject_reason && (<><dt>Reject reason</dt><dd>{humanize(c.reject_reason)}</dd></>)}
        </dl>
        <textarea placeholder="Note (required to confirm, reject or reopen)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Note" />
        {acts.includes('reject') && (
          <select value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reject reason">
            <option value="">Reject reason…</option>
            {d.reject_reasons.map((r) => <option key={r} value={r}>{humanize(r)}</option>)}
          </select>
        )}
        {acts.includes('assign') && (
          <div className="row">
            <select value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Assignee">
              <option value="r.das">r.das (Circle Officer)</option>
              <option value="s.bora">s.bora (District supervisor)</option>
              <option value="field.team.kamrup">Field team, Kamrup</option>
            </select>
            <button className="btn" disabled={busy} onClick={() => act('assign')}>Assign</button>
          </div>
        )}
        <div className="row wrap">
          {acts.filter((a) => a !== 'assign').map((a) => (
            <button key={a} className={`btn${a === 'confirm' || a === 'start_review' ? ' primary' : ''}${a === 'reject' ? ' danger' : ''}`} disabled={busy} onClick={() => act(a)}>
              {ACTION_LABEL[a] ?? a}
            </button>
          ))}
          <button className="btn" disabled={busy || !note.trim()} onClick={() => act('add_note')}>Add note</button>
        </div>
        {acts.length === 0 && (
          <p className="small muted" style={{ margin: 0 }}>
            {c.status === 'CONFIRMED' || c.status === 'REJECTED'
              ? 'Decision recorded. Only a supervisor can reopen this case.'
              : `The ${role} role cannot change this case's status. Switch role in the top bar to act as a reviewer.`}
          </p>
        )}
        <div className="row small">
          <input type="file" accept="image/*,.pdf,.geojson,.json,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} aria-label="Attach field evidence" />
          <button className="btn sm" disabled={!file || busy} onClick={upload}>Attach evidence</button>
        </div>
        {err && <p className="error">{err}</p>}
      </div>
    </Panel>
  )
}
