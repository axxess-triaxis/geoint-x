import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useApp } from '../app-context'
import { Loading, Panel } from '../components/ui'
import { fmtPct, humanize } from '../theme'
import type { Candidate, Decision } from '../types'

const TERM_COLOR: Record<string, string> = {
  change_likelihood: '#2a78d6',
  staleness: '#eb6834',
  urgency: '#1baf7a',
  coverage_fairness: '#eda100',
}

export default function Agent() {
  const { version, bump } = useApp()
  const [plan, setPlan] = useState<{ now: string; candidates: Candidate[] } | null>(null)
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [strategy, setStrategy] = useState('marginal_value')
  const [busy, setBusy] = useState(false)
  const [last, setLast] = useState<{ decision: Decision; case_ids: string[] } | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.plan().then(setPlan)
    api.decisions().then(setDecisions)
  }, [version])

  const cycle = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.cycle(strategy)
      setLast(r)
      bump()
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!plan) return <Loading what="Planning" />
  return (
    <div className="grid">
      <Panel
        title="Next observation candidates"
        sub="legal actions only: each is a real, captured Sentinel-2 scene newer than the area's last analysed observation"
        right={
          <>
            <select value={strategy} onChange={(e) => setStrategy(e.target.value)} aria-label="Strategy">
              <option value="marginal_value">Marginal value per cost</option>
              <option value="round_robin">Round robin (baseline)</option>
              <option value="llm_assisted">LLM-assisted (allowlisted)</option>
            </select>
            <button className="btn primary" onClick={cycle} disabled={busy}>{busy ? 'Running cycle…' : 'Run monitoring cycle'}</button>
          </>
        }
        pad={false}
      >
        {err && <p className="error" style={{ padding: 12 }}>{err}</p>}
        {last && (
          <div className="banner" style={{ margin: 12 }}>
            <b>Decision ({humanize(last.decision.decision_source)}):</b> {last.decision.reason}
            {last.decision.executed_run_id && (
              <> Ran <code>{last.decision.executed_run_id}</code>, {last.case_ids.length} new case(s){' '}
                {last.case_ids.slice(0, 5).map((id) => <Link key={id} to={`/cases/${id}`} style={{ marginRight: 6 }}>{id}</Link>)}
              </>
            )}
          </div>
        )}
        {plan.candidates.length === 0 ? (
          <p className="muted" style={{ padding: 12, margin: 0 }}>
            No monitored area has a new usable observation beyond what has already been analysed. The agent waits rather than
            inventing data. (In live mode this list would refresh as new Sentinel-2 acquisitions arrive, every ~5 days.)
          </p>
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>Area</th><th>Compare</th><th>Value terms (weighted)</th><th className="num">P(usable)</th><th className="num">Cost</th><th className="num">Score</th>
              </tr>
            </thead>
            <tbody>
              {plan.candidates.map((c, i) => (
                <tr key={c.key} className={i === 0 ? 'sel' : ''}>
                  <td><b>{c.aoi_name}</b><div className="small muted">{c.district}</div></td>
                  <td className="small">{c.prev_date} → <b>{c.next_date}</b><div className="mono muted">{c.next_scene_id.slice(0, 24)}</div></td>
                  <td style={{ minWidth: 260 }}>
                    <div style={{ display: 'flex', gap: 2, height: 10 }}>
                      {Object.entries(c.terms).map(([k, v]) => (
                        <span key={k} title={`${humanize(k)}: ${v.toFixed(2)} × ${c.weights[k]}`} style={{ width: `${v * c.weights[k] * 100}%`, background: TERM_COLOR[k] }} />
                      ))}
                    </div>
                    <div className="small muted" style={{ marginTop: 3 }}>
                      {Object.entries(c.terms).map(([k, v]) => `${humanize(k)} ${v.toFixed(2)}`).join(' · ')}
                    </div>
                    {c.notes.map((n) => <div key={n} className="small muted">{n}</div>)}
                  </td>
                  <td className="num">{fmtPct(c.p_usable, 1)}</td>
                  <td className="num">{c.cost.toFixed(2)}</td>
                  <td className="num"><b>{c.score.toFixed(3)}</b></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row wrap small ink2" style={{ gap: 12, padding: '8px 12px' }}>
          {Object.entries(TERM_COLOR).map(([k, col]) => (
            <span key={k} className="row" style={{ gap: 5 }}><span className="swatch" style={{ background: col }} />{humanize(k)}</span>
          ))}
          <span className="muted">score = Σ(weight × term) × P(usable) ÷ cost</span>
        </div>
      </Panel>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1fr)' }}>
        <Panel title="How the agent decides">
          <ul className="small ink2" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.6 }}>
            <li><b>Change likelihood</b>: Beta posterior of reviewer outcomes in the area (confirmed vs rejected), blended with recent changed hectares per km².</li>
            <li><b>Staleness</b>: 1 − exp(−days since last analysed observation ÷ target revisit).</li>
            <li><b>Urgency</b>: 1 − historical share of ≤20% cloud acquisitions in the next 60 days (same calendar window, real catalogue). Before the monsoon, clear windows are scarce.</li>
            <li><b>Coverage fairness</b>: gain in Jain evenness of analyses across all monitored districts.</li>
            <li><b>P(usable)</b>: measured clear-sky fraction of the candidate scene over the area (SCL).</li>
            <li>An LLM may only pick among these candidates; any other answer is rejected and the deterministic choice is used.</li>
          </ul>
        </Panel>
        <Panel title="Decision log" pad={false}>
          <table className="data">
            <thead><tr><th>Time</th><th>Strategy</th><th>Source</th><th>Decision</th></tr></thead>
            <tbody>
              {decisions.slice(0, 12).map((d) => (
                <tr key={d.id}>
                  <td className="small">{new Date(d.ts).toLocaleString('en-GB')}</td>
                  <td className="small">{humanize(d.strategy)}</td>
                  <td className="small">{humanize(d.decision_source)}</td>
                  <td className="small">{d.reason}{d.executed_run_id && <> → <code>{d.executed_run_id}</code></>}</td>
                </tr>
              ))}
              {!decisions.length && <tr><td colSpan={4} className="muted">No cycles run yet.</td></tr>}
            </tbody>
          </table>
        </Panel>
      </div>
    </div>
  )
}
