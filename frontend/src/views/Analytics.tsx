import { useEffect, useState } from 'react'
import { api } from '../api'
import { useApp } from '../app-context'
import { BarList, LineChart, StackedRows } from '../components/Charts'
import { Kpi, Loading, Panel } from '../components/ui'
import { T, TRANSITIONS, fmtDate, fmtPct, humanize } from '../theme'
import type { Analytics as A, Aoi } from '../types'

const COMPOSITION = [
  { key: 'water', label: 'Open water', color: '#2a78d6' },
  { key: 'bare_or_built', label: 'Bare / built-up', color: '#eb6834' },
]

export default function Analytics() {
  const { version } = useApp()
  const [a, setA] = useState<A | null>(null)
  const [aois, setAois] = useState<Aoi[]>([])
  useEffect(() => {
    api.analytics().then(setA)
    api.aois().then(setAois)
  }, [version])
  if (!a) return <Loading what="Computing analytics" />
  const t = a.totals
  const name = (id: string) => aois.find((x) => x.id === id)?.name ?? id

  const byClass = TRANSITIONS.filter((x) => a.by_transition[x.id]).map((x) => ({
    key: x.id,
    label: x.short,
    value: a.by_transition[x.id].area_ha,
    color: x.color,
    detail: `${a.by_transition[x.id].regions} regions, ${a.by_transition[x.id].cases} cases`,
  }))
  const byDistrict = Object.entries(a.by_district)
    .sort((p, q) => q[1].area_ha - p[1].area_ha)
    .map(([k, v]) => ({ key: k, label: k, value: v.area_ha, color: '#2a78d6', detail: `${v.regions} regions` }))
  const periods = Object.keys(a.by_period).sort()

  return (
    <div className="grid">
      <section className="panel kpis">
        <Kpi label="Detected change regions" value={t.regions} sub={`${t.changed_area_ha.toFixed(0)} ha, all analyses`} />
        <Kpi label="Open cases" value={t.open} sub={`${t.cases} cases · ${t.p1_open} open at P1`} />
        <Kpi label="Confirmed" value={t.confirmed} />
        <Kpi label="Rejected" value={t.rejected} />
        <Kpi label="Rejection rate" value={t.rejection_rate == null ? '—' : fmtPct(t.rejection_rate)} sub="false-positive proxy, decided cases only" />
        <Kpi label="Analyses" value={t.analyses} sub={`${t.monitored_areas} monitored areas`} />
      </section>

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <Panel title="Detected change by category" sub="hectares, all recorded regions, all analyses">
          <BarList items={byClass} unit="ha" />
        </Panel>
        <Panel title="Detected change by district" sub="hectares · district per geoBoundaries 2021, not an official determination">
          <BarList items={byDistrict} unit="ha" />
        </Panel>
      </div>

      <Panel title="Land composition over time" sub="share of clear pixels, one mid-January Sentinel-2 observation per year · heuristic spectral classes">
        <div className="grid" style={{ gridTemplateColumns: `repeat(${Math.min(3, Object.keys(a.land_composition).length)}, minmax(0, 1fr))` }}>
          {Object.entries(a.land_composition).map(([aoi, rows]) => (
            <div key={aoi}>
              <h3 style={{ marginBottom: 4 }}>{name(aoi)}</h3>
              <LineChart
                x={rows.map((r) => r.date.slice(0, 4))}
                series={COMPOSITION.map((c) => ({ key: c.key, label: c.label, color: c.color, values: rows.map((r) => r.shares[c.key] ?? null) }))}
                height={180}
              />
            </div>
          ))}
        </div>
        <p className="small muted" style={{ margin: '8px 0 0' }}>{a.notes[0]}</p>
      </Panel>

      <div className="grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
        <Panel title="Verification outcomes by category" sub="cases">
          <StackedRows
            rows={TRANSITIONS.filter((x) => a.by_transition[x.id]).map((x) => {
              const b = a.by_transition[x.id]
              return { key: x.id, label: x.short, values: { open: b.cases - b.confirmed - b.rejected, confirmed: b.confirmed, rejected: b.rejected } }
            })}
            segments={[
              { key: 'confirmed', label: 'Confirmed', color: '#0ca30c' },
              { key: 'rejected', label: 'Rejected', color: '#898781' },
              { key: 'open', label: 'Open', color: '#86b6ef' },
            ]}
          />
          {Object.keys(a.reject_reasons).length > 0 && (
            <>
              <h3 style={{ margin: '14px 0 6px' }}>Rejection reasons</h3>
              <BarList items={Object.entries(a.reject_reasons).map(([k, v]) => ({ key: k, label: humanize(k), value: v, color: '#898781' }))} unit="cases" />
            </>
          )}
        </Panel>
        <Panel title="Detected change by observation period" sub="hectares by category, per analysed period">
          {periods.length ? (
            <StackedRows
              rows={periods.map((p) => ({ key: p, label: p.replace('-', ' → '), values: Object.fromEntries(Object.entries(a.by_period[p]).map(([k, v]) => [k, Math.round(v * 10) / 10])) }))}
              segments={TRANSITIONS.filter((x) => periods.some((p) => a.by_period[p][x.id])).map((x) => ({ key: x.id, label: T[x.id].short, color: x.color }))}
            />
          ) : (
            <p className="muted small">No analyses yet.</p>
          )}
        </Panel>
      </div>

      <Panel title="Monitoring coverage" sub="real Sentinel-2 L2A acquisition catalogue per area" pad={false}>
        <table className="data">
          <thead>
            <tr>
              <th>Area</th><th>Mode</th><th>District</th><th className="num">km²</th><th className="num">Acquisitions</th>
              <th className="num">≤20% cloud</th><th className="num">Analyses</th><th>Last observed</th><th className="num">Days since</th>
            </tr>
          </thead>
          <tbody>
            {a.coverage.map((c) => (
              <tr key={c.aoi_id}>
                <td>{c.name}</td>
                <td className="small">{c.mode === 'encroachment' ? 'Encroachment' : 'LULC'}</td>
                <td>{c.district ?? '—'}</td>
                <td className="num">{c.area_km2}</td>
                <td className="num">{c.catalog_acquisitions}</td>
                <td className="num">{fmtPct(c.catalog_clear_share)}</td>
                <td className="num">{c.analyses}</td>
                <td>{c.last_observed ? fmtDate(c.last_observed) : <span className="muted">never</span>}</td>
                <td className="num">{c.days_since_observation ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  )
}
