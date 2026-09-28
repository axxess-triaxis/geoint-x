import { useEffect, useMemo, useState } from 'react'
import { NavLink, Route, Routes, useLocation } from 'react-router-dom'
import { api, setIdentity } from './api'
import { Ctx, DEMO_USERS } from './app-context'
import { Icon } from './components/icons'
import { fmtDate } from './theme'
import type { Meta, Role } from './types'
import Agent from './views/Agent'
import Analytics from './views/Analytics'
import Assistant from './views/Assistant'
import CaseDetail from './views/CaseDetail'
import Cases from './views/Cases'
import Monitoring from './views/Monitoring'
import Overview from './views/Overview'
import Workspace from './views/Workspace'

const TITLES: Record<string, [string, string]> = {
  '': ['Overview', 'Monitored areas, open cases and recent activity'],
  map: ['Change detection', 'Land use / land cover change across monitored areas (NESFIC-D-21)'],
  monitoring: ['Encroachment monitoring', 'Government land and wetland boundaries (NESFIC-D-17)'],
  cases: ['Cases', 'Verification queue for suspected changes'],
  analytics: ['Analytics', 'Change, verification outcomes and monitoring coverage'],
  assistant: ['AI assistant', 'Questions answered from recorded findings only'],
  agent: ['Monitoring agent', 'Where should the system look next?'],
}

export default function App() {
  const [meta, setMeta] = useState<Meta | null>(null)
  const [role, setRoleState] = useState<Role>(() => {
    try {
      return (localStorage.getItem('geointx.role') as Role) || 'analyst'
    } catch {
      return 'analyst'
    }
  })
  const [version, setVersion] = useState(0)
  const user = DEMO_USERS[role].split(' ')[0]
  setIdentity(user, role)

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null))
  }, [])

  const ctx = useMemo(
    () => ({
      meta,
      role,
      user,
      setRole: (r: Role) => {
        setRoleState(r)
        try {
          localStorage.setItem('geointx.role', r)
        } catch {
          /* storage unavailable */
        }
        setVersion((v) => v + 1)
      },
      version,
      bump: () => setVersion((v) => v + 1),
    }),
    [meta, role, user, version],
  )

  const loc = useLocation()
  const section = loc.pathname.split('/')[1] ?? ''
  const [title, sub] = TITLES[section] ?? TITLES['']
  const flush = section === 'map' || section === 'monitoring'

  return (
    <Ctx.Provider value={ctx}>
      <div className="shell">
        <nav className="nav" aria-label="Main">
          <div className="brand">
            <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden>
              <rect width="32" height="32" rx="6" fill="#262a2f" />
              <path d="M6 22 L13 12 L18 18 L26 8" fill="none" stroke="#eb6834" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
              <circle cx="26" cy="8" r="3" fill="#86b6ef" />
            </svg>
            <div>
              <b>GEOINT-X</b>
              <small>Change intelligence · Assam</small>
            </div>
          </div>
          <NavLink to="/" end><Icon.overview />Overview</NavLink>
          <div className="sep">Detect</div>
          <NavLink to="/map"><Icon.map />Change detection</NavLink>
          <NavLink to="/monitoring"><Icon.shield />Encroachment</NavLink>
          <div className="sep">Verify</div>
          <NavLink to="/cases"><Icon.cases />Cases</NavLink>
          <NavLink to="/assistant"><Icon.chat />AI assistant</NavLink>
          <div className="sep">Monitor</div>
          <NavLink to="/agent"><Icon.agent />Monitoring agent</NavLink>
          <NavLink to="/analytics"><Icon.chart />Analytics</NavLink>
          <div className="foot">
            Prototype for NESFIC-D-21 and NESFIC-D-17.
            <br />
            AI flags suspected change; officials decide.
          </div>
        </nav>
        <div className="main">
          <header className="topbar">
            <div className="title">
              <h1>{title}</h1>
              <small>{sub}</small>
            </div>
            <span className="spacer" />
            {meta && (
              <span
                className="chip"
                title={`${meta.pack_note ?? ''}\n${Object.values(meta.sources).join('\n')}`}
              >
                <span className="dot" style={{ background: '#eda100' }} />
                Demo pack · real Sentinel-2 · captured {fmtDate(meta.pack_built_at)}
              </span>
            )}
            {meta && (
              <span className="chip" title={meta.ai.enabled ? `Model ${meta.ai.model}` : 'No API key: deterministic templates are used'}>
                <span className="dot" style={{ background: meta.ai.enabled ? '#1baf7a' : '#898781' }} />
                {meta.ai.enabled ? `AI: ${meta.ai.provider}` : 'AI: template mode'}
              </span>
            )}
            <label className="row small ink2" title="Demo role switcher. This is not authentication.">
              Acting as
              <select value={role} onChange={(e) => ctx.setRole(e.target.value as Role)} aria-label="Demo role">
                {(Object.keys(DEMO_USERS) as Role[]).map((r) => (
                  <option key={r} value={r}>
                    {DEMO_USERS[r]}
                  </option>
                ))}
              </select>
            </label>
          </header>
          <main className={`content${flush ? ' flush' : ''}`}>
            <Routes>
              <Route path="/" element={<Overview />} />
              <Route path="/map" element={<Workspace />} />
              <Route path="/monitoring" element={<Monitoring />} />
              <Route path="/cases" element={<Cases />} />
              <Route path="/cases/:id" element={<CaseDetail />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/assistant" element={<Assistant />} />
              <Route path="/agent" element={<Agent />} />
            </Routes>
          </main>
        </div>
      </div>
    </Ctx.Provider>
  )
}
