import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { Panel } from '../components/ui'
import type { AssistantReply } from '../types'

const SUGGESTIONS = [
  'Show me significant land-use changes in Kamrup during the last six months.',
  'Which monitored wetlands have the largest detected changes?',
  'Why was CASE-0001 prioritised?',
  'Show the evidence for CASE-0001.',
  'Summarise land-use changes around Deepor Beel.',
  'Change by district',
  'Show confirmed cases',
]

export default function Assistant() {
  const [log, setLog] = useState<AssistantReply[]>([])
  const [q, setQ] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const ask = async (question: string) => {
    if (!question.trim()) return
    setBusy(true)
    setErr(null)
    try {
      const r = await api.ask(question)
      setLog((l) => [...l, r])
      setQ('')
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) 300px', alignItems: 'start' }}>
      <Panel title="Ask about detected changes" sub="answers are built from recorded findings via allowlisted query tools">
        <div className="chat">
          {log.length === 0 && (
            <p className="muted" style={{ margin: 0 }}>
              The assistant selects one deterministic query (list, case evidence, aggregate, boundary ranking, area summary), runs it,
              and phrases the answer from the result. Case ids and figures in an AI answer are checked against the query result;
              if a check fails, a template answer is shown instead.
            </p>
          )}
          {log.map((r, i) => (
            <div key={i} className="stack">
              <div className="msg q">{r.question}</div>
              <div className="msg a">
                {linkify(r.answer)}
                <div className="small muted" style={{ marginTop: 8, whiteSpace: 'normal' }}>
                  Tool <code>{r.tool}</code> {Object.keys(r.args).length > 0 && <code>{JSON.stringify(stripNull(r.args))}</code>} ·
                  routed by {r.route_source} · answer from {r.answer_source}
                  {r.guard_problems.length > 0 && <> · guard: {r.guard_problems.join('; ')}</>}
                </div>
                {r.focus_case_ids.length > 0 && (
                  <div className="row wrap small" style={{ marginTop: 6, whiteSpace: 'normal' }}>
                    {r.focus_case_ids.slice(0, 10).map((id) => (
                      <Link key={id} className="chip" to={`/cases/${id}`}>{id}</Link>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
        <form
          className="row"
          style={{ marginTop: 14 }}
          onSubmit={(e) => {
            e.preventDefault()
            ask(q)
          }}
        >
          <input style={{ flex: 1 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask a question about detected changes…" aria-label="Question" />
          <button className="btn primary" disabled={busy || !q.trim()}>{busy ? 'Working…' : 'Ask'}</button>
        </form>
        {err && <p className="error">{err}</p>}
      </Panel>
      <Panel title="Try">
        <div className="suggest">
          {SUGGESTIONS.map((s) => (
            <button key={s} onClick={() => ask(s)} disabled={busy}>{s}</button>
          ))}
        </div>
      </Panel>
    </div>
  )
}

function linkify(text: string) {
  const parts = text.split(/(CASE-\d{4})/g)
  return parts.map((p, i) => (/^CASE-\d{4}$/.test(p) ? <Link key={i} to={`/cases/${p}`}>{p}</Link> : <span key={i}>{p}</span>))
}

function stripNull(o: Record<string, unknown>) {
  return Object.fromEntries(Object.entries(o).filter(([, v]) => v != null))
}
