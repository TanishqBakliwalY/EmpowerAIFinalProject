/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from 'react'
import { LoaderCircle, RefreshCw } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Section, fmtDateTime, fmtUsd } from '../lib'

const CARDS: [string, string, string][] = [
  ['extraction', 'Requirement extraction', 'Fields the Requirements Analyst got right on 5 labelled briefs (type, compliance, budget, deadline, integrations, questions).'],
  ['scope', 'Scope classification', 'Scope Guard decided "billable change or not" correctly on 12 labelled client messages.'],
  ['estimate', 'Effort estimate error', 'Mean absolute error vs actual hours on 6 past projects (lower is better).'],
  ['pricing', 'Pricing & margin correctness', 'Calculator vs an independent re-implementation of the pricing policy, including discount caps and approvals.'],
  ['staffing', 'Staffing feasibility', 'Proposed teams where every person exists, is free for the allocation and every role is covered.'],
  ['risk', 'Risk detection', 'Project Health flags vs the problems planted in the synthetic delivery data.'],
  ['proposal', 'Proposal completeness', 'Required sections present (scope, exclusions, timeline, team, pricing, milestones, assumptions, questions, risks).'],
]

export default function EvaluationPage() {
  const { user } = useAuth()
  const [d, setD] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const load = () => api.get<any>('/api/evaluation').then(setD).catch(() => setD({ latest: null, history: [] }))
  useEffect(() => { void load() }, [])
  const rerun = async () => {
    setBusy(true)
    await api.post('/api/evaluation/run', {}).catch(() => {})
    await load()
    setBusy(false)
  }
  const L = d?.latest
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Administration</div>
          <h1>Evaluation</h1>
          <div className="sub">How well the agents do on a small labelled benchmark and on this installation's own runs. All data is synthetic, so these
            numbers measure the method, not performance on Empower's real projects. Re-run with <code>python scripts/evaluate.py --live</code>.</div>
        </div>
        {user?.role === 'director' && <button className="btn" disabled={busy} onClick={rerun}>{busy ? <LoaderCircle size={15} className="spin" /> : <RefreshCw size={15} />} Re-run free checks</button>}
      </div>
      {!d && <div className="card empty"><span className="spinner" /></div>}
      {d && !L && <div className="card empty">No evaluation results yet. Run <code>python scripts/evaluate.py --live</code>.</div>}
      {L && (
        <>
          <div className="notice blue small">Latest result: version <b>{L.version}</b>, {fmtDateTime(L.at)}{L.trigger ? ` by ${L.trigger}` : ''}. Synthetic benchmark.</div>
          <div className="grid g4">
            {CARDS.filter(([k]) => L[k]).map(([k, title, text]) => {
              const r = L[k]
              const good = k === 'estimate' ? r.value_pct <= r.baseline_pct + 5 : (r.value_pct ?? 0) >= 85
              return (
                <div key={k} className="card card-pad col" style={{ gap: 6 }}>
                  <div className="small muted strong">{title}</div>
                  <div className="metric-big">{k === 'risk' ? `P ${r.precision} · R ${r.recall}` : `${r.value_pct ?? '–'}%`}</div>
                  <div className="tiny">
                    <span className={`sev ${good ? 'green' : 'amber'}`}>{k === 'estimate' ? (good ? 'close to baseline' : 'worse than baseline') : good ? 'meets target' : 'below target'}</span>{' '}
                    {r.live ? <span className="sev blue">model run</span> : <span className="sev neutral">code / records</span>}
                    {r.from_run && <span className="tiny muted"> from {fmtDateTime(r.from_run)}</span>}
                  </div>
                  <div className="tiny muted">{text}{k === 'estimate' ? ` Empower's original estimates: ${r.baseline_pct}%, but always low (−${r.baseline_pct}% bias); the app's errors lean high (${(r.history?.at(-1)?.app_mean_bias_pct ?? 0) > 0 ? '+' : ''}${r.history?.at(-1)?.app_mean_bias_pct ?? '?'}%), the safer side on a fixed price.` : ''}{r.cost_usd ? ` Cost ${fmtUsd(r.cost_usd, 3)}.` : ''}</div>
                </div>
              )
            })}
          </div>
          {L.scope && (
            <Section title="Scope classification, message by message">
              <table className="tbl"><thead><tr><th>Message</th><th>Expected</th><th>Got</th><th className="right">Change requests</th><th>Correct</th></tr></thead>
                <tbody>{L.scope.rows.map((r: any) => (
                  <tr key={r.id}><td>{r.id}{r.injection_removed ? <span className="tiny muted"> (injection removed)</span> : ''}</td><td>{r.expected_billable ? 'billable change' : 'no charge'}</td>
                    <td>{r.got_billable ? 'billable change' : 'no charge'}</td><td className="right">{r.change_requests}</td>
                    <td><span className={`sev ${r.correct ? 'green' : 'red'}`}>{r.correct ? 'yes' : 'no'}</span></td></tr>
                ))}</tbody></table>
            </Section>
          )}
          {L.estimate?.history && (
            <Section title="Estimator versions (backtest on 6 past projects)">
              <table className="tbl"><thead><tr><th>Version</th><th>Effort</th><th className="right">Error (MAPE)</th><th className="right">Bias</th><th className="right">Actual within range</th><th className="right">Seconds</th></tr></thead>
                <tbody>{L.estimate.history.map((h: any, i: number) => (
                  <tr key={i}><td>{h.estimator_version}</td><td>{h.effort}</td><td className="right">{h.app_mape_pct}%</td><td className="right">{h.app_mean_bias_pct > 0 ? '+' : ''}{h.app_mean_bias_pct}%</td>
                    <td className="right">{h.actual_within_app_range}/6</td><td className="right">{h.avg_seconds}</td></tr>
                ))}
                  <tr><td className="muted">Empower's original estimates</td><td /><td className="right muted">{L.estimate.baseline_pct}%</td><td className="right muted">−{L.estimate.baseline_pct}%</td><td /><td /></tr></tbody></table>
            </Section>
          )}
          {L.operations && (
            <Section title="Operations on this installation (excluding shipped examples)">
              <table className="tbl"><thead><tr><th>Module</th><th className="right">Runs</th><th className="right">Completed</th><th className="right">Failed</th><th className="right">Median time</th><th className="right">Mean cost</th><th className="right">Approved</th><th className="right">Revised by agents</th></tr></thead>
                <tbody>{L.operations.rows.map((r: any) => (
                  <tr key={r.module}><td>{r.module}</td><td className="right">{r.runs}</td><td className="right">{r.completed_pct ?? '–'}%</td><td className="right">{r.failed_pct ?? '–'}%</td>
                    <td className="right">{r.median_seconds != null ? `${r.median_seconds} s` : '–'}</td><td className="right mono">{fmtUsd(r.mean_cost_usd, 4)}</td>
                    <td className="right">{r.decided ? `${r.approved_pct}% of ${r.decided}` : '–'}</td><td className="right">{r.revised_pct != null ? `${r.revised_pct}%` : '–'}</td></tr>
                ))}</tbody></table>
            </Section>
          )}
          {L.risk && <div className="small muted">{L.risk.caveat}</div>}
        </>
      )}
      {d?.history?.length > 0 && (
        <Section title="History">
          <table className="tbl"><thead><tr><th>Run</th><th>Version</th><th className="right">Extraction</th><th className="right">Scope</th><th className="right">Estimate error</th><th className="right">Pricing</th><th className="right">Staffing</th><th className="right">Proposal</th></tr></thead>
            <tbody>{[...d.history].reverse().map((h: any) => (
              <tr key={h.file}><td className="small">{fmtDateTime(h.at)}</td><td>{h.version}</td><td className="right">{h.extraction ?? '–'}</td><td className="right">{h.scope ?? '–'}</td>
                <td className="right">{h.estimate ?? '–'}</td><td className="right">{h.pricing ?? '–'}</td><td className="right">{h.staffing ?? '–'}</td><td className="right">{h.proposal ?? '–'}</td></tr>
            ))}</tbody></table>
        </Section>
      )}
    </div>
  )
}
