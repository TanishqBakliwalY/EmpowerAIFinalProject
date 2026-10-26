/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from 'react'
import { ArrowLeft, Bot, LoaderCircle, Play } from 'lucide-react'
import { api } from '../api'
import { RecCard, SeverityBadge } from '../cards'
import { Bar, List, Section, Stat, fmtDate, fmtDateTime, fmtMoney, go, useHashParams } from '../lib'

type Signal = { kind: string; severity: string; finding: string; evidence: string; impact: string; recommendation: string }
type Project = {
  code: string; name: string; client: string; status: string; contract_type: string; currency: string; contract_value: number
  start: string; end: string; sow_id: string | null; level: string; signals: Signal[]
  metrics: { elapsed_pct: number; complete_pct: number; budget_hours: number; hours_booked: number; earned_hours: number; cpi: number | null
    spi: number | null; forecast_hours: number; overrun_hours: number; overrun_cost: number; forecast_end: string; team_size: number; planned_team_size: number }
  milestones: { name: string; planned: string; forecast: string; actual: string | null; status: string }[]
  dependencies: { item: string; owner: string; due: string; status: string }[]
  scope: { approved_cr_hours: number; approved_cr_value: number; pending_checks: number; clarifications: number; checks: any[] }
  review?: (Review & { run_id: string; at: string; run_status: string }) | null
  team?: { emp_id: string; name: string; role: string; level: string; allocation_pct: number; until: string }[]
  audit?: { ts: string; actor: string; action: string; summary: string }[]
}
type Review = { headline: string; why: string[]; mitigations: { action: string; owner: string; effect: string }[]; escalate: boolean
  escalation_reason: string | null; client_message: string | null; unknowns: string[] }

const MS: Record<string, string> = { done: 'Done', done_late: 'Done late', late: 'Overdue', at_risk: 'Forecast to slip', upcoming: 'Upcoming' }

export default function ProjectHealth({ code }: { code?: string }) {
  return code ? <Detail code={code} /> : <ListView />
}

function ListView() {
  const params = useHashParams()
  const [data, setData] = useState<{ projects: Project[]; note: string; as_of: string } | null>(null)
  const [onlyRisk, setOnlyRisk] = useState(params.level === 'risk')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { api.get<any>('/api/projects/health').then(setData).catch((e) => setErr(e.message)) }, [])
  const review = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.post<{ id: string }>('/api/projects/reviews', {})
      go(`/activity/${r.id}`)
    } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  const rows = (data?.projects ?? []).filter((p) => !onlyRisk || p.level !== 'ok')
  const atRisk = (data?.projects ?? []).filter((p) => p.level !== 'ok').length
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Delivery</div>
          <h1>Project Health</h1>
          <div className="sub">Every active project, scored by code from the delivery tracker: earned value (CPI/SPI), milestone slip, late client
            dependencies, staffing and scope signals. The Delivery Risk Agent then explains the risks and proposes mitigations for a person to approve.</div>
        </div>
        <button className="btn btn-primary" disabled={busy || !atRisk} onClick={review}>
          {busy ? <LoaderCircle size={15} className="spin" /> : <Bot size={15} />} Run delivery review ({atRisk} at risk)
        </button>
      </div>
      {data && <div className="notice blue small">{data.note} Indicators as of {fmtDate(data.as_of)}.</div>}
      {err && <div className="notice red small">{err}</div>}
      <div className="row">
        <button className={`btn btn-chip ${!onlyRisk ? 'active-chip' : ''}`} onClick={() => setOnlyRisk(false)}>All ({data?.projects.length ?? 0})</button>
        <button className={`btn btn-chip ${onlyRisk ? 'active-chip' : ''}`} onClick={() => setOnlyRisk(true)}>At risk ({atRisk})</button>
      </div>
      <div className="card">
        <table className="tbl">
          <thead><tr><th>Project</th><th>Status</th><th>Progress vs time</th><th className="right">CPI</th><th className="right">SPI</th><th className="right">Forecast overrun</th><th>Top signal</th></tr></thead>
          <tbody>
            {!data && <tr><td colSpan={7}><div className="empty"><span className="spinner" /></div></td></tr>}
            {rows.map((p) => (
              <tr key={p.code} className="click" onClick={() => go(`/projects/${p.code}`)}>
                <td><div className="strong">{p.code} · {p.name}</div><div className="tiny muted">{p.client} · {p.contract_type === 'fixed' ? 'fixed price' : 'T&M'} · {fmtMoney(p.currency, p.contract_value)}</div></td>
                <td><SeverityBadge s={p.level} />{p.status === 'starting' && <div className="tiny muted">starts {fmtDate(p.start)}</div>}</td>
                <td style={{ minWidth: 160 }}>
                  <div className="tiny muted">{p.metrics.complete_pct}% done · {p.metrics.elapsed_pct}% of time</div>
                  <Bar value={p.metrics.complete_pct} max={100} tone={p.metrics.complete_pct + 5 < p.metrics.elapsed_pct ? 'amber' : ''} />
                </td>
                <td className="right mono">{p.metrics.cpi ?? '–'}</td>
                <td className="right mono">{p.metrics.spi ?? '–'}</td>
                <td className="right">{p.metrics.overrun_hours ? <>{p.metrics.overrun_hours.toLocaleString()} h<div className="tiny muted">≈ {fmtMoney(p.currency, p.metrics.overrun_cost)}</div></> : '–'}</td>
                <td className="small" style={{ maxWidth: 320 }}>{p.signals[0]?.finding ?? <span className="muted">No signals</span>}
                  {p.review && <div className="tiny" style={{ color: 'var(--violet)' }}>Agent: {p.review.headline}</div>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Detail({ code }: { code: string }) {
  const [p, setP] = useState<Project | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.get<Project>(`/api/projects/health/${code}`).then(setP).catch((e) => setErr(e.message)) }, [code])
  if (err) return <div className="page"><div className="notice red">{err}</div></div>
  if (!p) return <div className="page"><div className="empty"><span className="spinner" /></div></div>
  const m = p.metrics
  const runAgent = async () => {
    setBusy(true)
    try {
      const r = await api.post<{ id: string }>('/api/projects/reviews', { codes: [p.code] })
      go(`/activity/${r.id}`)
    } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  return (
    <div className="page">
      <div className="page-head">
        <div style={{ flex: 1 }}>
          <a href="#/projects" className="small muted row" style={{ gap: 4 }}><ArrowLeft size={14} /> All projects</a>
          <h1 style={{ marginTop: 8 }}>{p.code} · {p.name}</h1>
          <div className="meta-line">
            <SeverityBadge s={p.level} />
            <span>{p.client}</span><span>{p.contract_type === 'fixed' ? 'Fixed price' : 'Time & materials'} {fmtMoney(p.currency, p.contract_value)}</span>
            <span>{fmtDate(p.start)} → {fmtDate(p.end)}</span>{p.sow_id && <a href="#/scope">{p.sow_id}</a>}
            <span className="pill">synthetic tracker data</span>
          </div>
        </div>
        {p.level !== 'ok' && (
          <button className="btn btn-primary" disabled={busy} onClick={runAgent}>{busy ? <LoaderCircle size={15} className="spin" /> : <Play size={15} />} Ask the Delivery Risk Agent</button>
        )}
      </div>
      <div className="grid g4">
        <Stat label="Progress vs time" value={`${m.complete_pct}% / ${m.elapsed_pct}%`} foot="reported completion / time elapsed" />
        <Stat label="Cost efficiency (CPI)" value={m.cpi ?? '–'} foot={`${m.hours_booked.toLocaleString()} h booked for ${m.earned_hours.toLocaleString()} h earned`} />
        <Stat label="Schedule efficiency (SPI)" value={m.spi ?? '–'} foot={`forecast finish ${fmtDate(m.forecast_end)}`} />
        <Stat label="Forecast overrun" value={m.overrun_hours ? `${m.overrun_hours.toLocaleString()} h` : 'none'} foot={m.overrun_cost ? `≈ ${fmtMoney(p.currency, m.overrun_cost)} internal cost (estimate)` : `budget ${m.budget_hours.toLocaleString()} h`} />
      </div>

      {p.review && (
        <Section title={<span className="row" style={{ gap: 8 }}><Bot size={16} color="var(--violet)" /> Delivery Risk Agent's review</span>}
          right={<span className="tiny muted">{fmtDateTime(p.review.at)} · <a href={`#/activity/${p.review.run_id}`}>trace</a></span>}>
          <p className="strong" style={{ marginBottom: 10 }}>{p.review.headline}</p>
          <div className="grid g2">
            <div><div className="tiny muted strong">WHY</div><List items={p.review.why} /></div>
            <div><div className="tiny muted strong">MITIGATIONS</div>
              <ul style={{ margin: 0, paddingLeft: 18 }}>{p.review.mitigations.map((x, i) => <li key={i}><b>{x.action}</b> <span className="tiny muted">({x.owner})</span><div className="small muted">{x.effect}</div></li>)}</ul>
            </div>
          </div>
          {p.review.escalate && <div className="notice amber small" style={{ marginTop: 12 }}><b>Escalate:</b> {p.review.escalation_reason}</div>}
          {p.review.client_message && <div className="notice blue small" style={{ marginTop: 8 }}><b>Note to the client (draft):</b> {p.review.client_message}</div>}
          {p.review.unknowns.length > 0 && <div className="small muted" style={{ marginTop: 8 }}><b>Unknown:</b> {p.review.unknowns.join('; ')}</div>}
        </Section>
      )}

      <div>
        <div className="section-head"><h2>Risk signals</h2><span className="muted small">Computed by code from the tracker, assignments and the Scope Guard ledger.</span></div>
        <div className="col" style={{ gap: 10 }}>
          {p.signals.length === 0 && <div className="card empty">No risk signals: on track.</div>}
          {p.signals.map((s, i) => (
            <RecCard key={i} r={{ severity: s.severity, title: s.finding, finding: s.finding, evidence: [s.evidence], impact: s.impact,
              recommendation: s.recommendation, confidence: { label: 'Computed', why: 'Arithmetic on tracker records (synthetic data); no model involved.' },
              agent: `Project Health · ${s.kind}` }} />
          ))}
        </div>
      </div>

      <div className="grid g2">
        <Section title="Milestones">
          <table className="tbl"><thead><tr><th>Milestone</th><th>Planned</th><th>Forecast</th><th>Status</th></tr></thead>
            <tbody>{p.milestones.map((x) => (
              <tr key={x.name}><td>{x.name}</td><td>{fmtDate(x.planned)}</td><td>{fmtDate(x.actual ?? x.forecast)}</td>
                <td><span className={`sev ${x.status === 'late' ? 'red' : x.status === 'at_risk' || x.status === 'done_late' ? 'amber' : x.status === 'done' ? 'green' : 'neutral'}`}>{MS[x.status] ?? x.status}</span></td></tr>
            ))}</tbody></table>
          {p.dependencies.length > 0 && (<>
            <div className="tiny muted strong" style={{ marginTop: 12 }}>DEPENDENCIES</div>
            <List items={p.dependencies.map((d) => `${d.item} (${d.owner}) due ${fmtDate(d.due)}: ${d.status}`)} />
          </>)}
        </Section>
        <Section title={`Team (${p.team?.length ?? 0}${p.status === 'starting' ? ` of ${m.planned_team_size} planned` : ''})`}>
          <table className="tbl"><thead><tr><th>Person</th><th>Role</th><th className="right">Allocation</th><th>Until</th></tr></thead>
            <tbody>{(p.team ?? []).map((t) => <tr key={t.emp_id}><td>{t.name}</td><td>{t.role}</td><td className="right">{t.allocation_pct}%</td><td>{fmtDate(t.until)}</td></tr>)}</tbody></table>
          <div className="tiny muted strong" style={{ marginTop: 12 }}>SCOPE (from Scope Guard)</div>
          <div className="small">{p.scope.approved_cr_hours} h approved in change requests ({fmtMoney(p.currency, p.scope.approved_cr_value)}) · {p.scope.pending_checks} awaiting a decision · {p.scope.clarifications} waiting on the client</div>
        </Section>
      </div>
      {p.audit && p.audit.length > 0 && (
        <Section title="Audit trail"><List items={p.audit.map((a) => `${fmtDateTime(a.ts)} · ${a.actor}: ${a.summary}`)} /></Section>
      )}
    </div>
  )
}
