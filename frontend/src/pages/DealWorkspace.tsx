/* eslint-disable @typescript-eslint/no-explicit-any */
// The Deal Desk as a guided workspace: five stages, outstanding questions and blockers, a scenario editor that
// recomputes dependent numbers in code, and the agents' collaboration (who sent what to whom).
import { useEffect, useState } from 'react'
import { ArrowRightLeft, Calculator, Check, Flag, LoaderCircle, Play, Save, UserCheck } from 'lucide-react'
import { api } from '../api'
import { Section, fmtDate, fmtMoney } from '../lib'
import type { Deal, Step } from '../types'

export const STAGES = [
  { key: 'Requirements', title: 'Requirements', steps: ['screen', 'analyst'] },
  { key: 'Feasibility', title: 'Feasibility', steps: ['architect', 'estimator'] },
  { key: 'Staffing', title: 'Staffing', steps: ['staffing'] },
  { key: 'Pricing', title: 'Pricing', steps: ['pricing', 'orchestrator'] },
  { key: 'Proposal', title: 'Proposal', steps: ['critic', 'writer', 'guard'] },
] as const

function stageStatus(steps: Record<string, Step>, keys: readonly string[]) {
  const ss = keys.map((k) => steps[k]).filter(Boolean)
  if (ss.some((s) => s.status === 'running')) return 'running'
  if (ss.some((s) => s.status === 'failed')) return 'failed'
  if (ss.length && ss.every((s) => s.status === 'done' || s.status === 'skipped')) return 'done'
  return 'pending'
}

export function StageBar({ deal, tab, setTab }: { deal: Deal; tab: string; setTab: (t: any) => void }) {
  const r: any = deal.results
  const sub: Record<string, string> = {
    Requirements: r.spec ? `${r.spec.features.length} features · ${r.spec.open_questions.length} open questions` : 'extracting…',
    Feasibility: r.estimate ? `${Math.round(r.estimate.total_hours).toLocaleString()} h · ${(r.design?.feasibility ?? '').replace(/_/g, ' ')}` : 'estimating…',
    Staffing: r.schedule ? `${r.schedule.team.length} people · ${r.schedule.meets_deadline === false ? 'misses deadline' : `go-live ${fmtDate(r.schedule.end_date)}`}` : 'planning…',
    Pricing: r.quote ? `${fmtMoney(r.quote.currency, r.quote.options.find((o: any) => o.model === r.quote.recommended_model)?.price)} ${r.quote.recommended_model === 'fixed' ? 'fixed' : 'T&M'}` : 'pricing…',
    Proposal: r.proposal_stale ? 'out of date: re-running' : r.review ? `critic: ${r.review.verdict}${r.leak_findings?.length ? ' · leak guard redacted' : ''}` : 'reviewing…',
  }
  return (
    <div className="stage-bar">
      {STAGES.map((s, i) => {
        const st = stageStatus(deal.steps as any, s.steps)
        return (
          <button key={s.key} className={`stage ${st} ${tab === s.key ? 'active' : ''}`} onClick={() => setTab(s.key)}>
            <span className="stage-num">{st === 'done' ? <Check size={13} strokeWidth={3} /> : st === 'running' ? <LoaderCircle size={13} className="spin" /> : i + 1}</span>
            <span style={{ minWidth: 0 }}>
              <span className="stage-title" style={{ display: 'block' }}>{i + 1}. {s.title}</span>
              <span className="stage-sub" style={{ display: 'block' }}>{sub[s.key]}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

export function Blockers({ deal }: { deal: Deal }) {
  const r: any = deal.results
  if (!r.spec) return null
  const items: [string, string][] = []
  if (r.proposal_stale) items.push(['amber', 'Assumptions changed: the Deal Critic and the Proposal Writer are re-running; the proposal below is out of date.'])
  if (r.schedule?.uncovered_roles?.length) items.push(['red', `No one free for: ${r.schedule.uncovered_roles.join(', ')} (hire, subcontract or re-plan).`])
  if (r.schedule?.meets_deadline === false) items.push(['amber', `Full scope goes live ${fmtDate(r.schedule.end_date)}, after the client's deadline${r.phase1 ? `; Phase 1 goes live ${fmtDate(r.phase1.go_live)}` : ''}.`])
  if (r.quote?.budget_fit && /above/i.test(r.quote.budget_fit)) items.push(['amber', r.quote.budget_fit])
  for (const a of r.quote?.approval_reasons ?? []) items.push(['amber', `Needs a Director: ${a}`])
  if (r.leak_findings?.length) items.push(['red', 'The leak guard redacted lines in the proposal; re-run before approving.'])
  const qs: string[] = r.spec.open_questions ?? []
  return (
    <Section title="Outstanding questions and blockers" right={<span className="tiny muted">{qs.length} question(s) for the client · {items.length} blocker(s)</span>}>
      <div className="grid g2">
        <div>
          <div className="tiny muted strong">BLOCKERS AND CHECKS</div>
          {items.length === 0 ? <div className="small"><span className="sev green">clear</span> Nothing blocks a decision.</div>
            : <ul style={{ margin: 0, paddingLeft: 18 }}>{items.map(([tone, t], i) => <li key={i} className="small"><span className={`sev ${tone}`}>{tone === 'red' ? 'blocker' : 'check'}</span> {t}</li>)}</ul>}
        </div>
        <div>
          <div className="tiny muted strong">ASK THE CLIENT BEFORE COMMITTING</div>
          <ol style={{ margin: 0, paddingLeft: 18 }}>{qs.slice(0, 5).map((q, i) => <li key={i} className="small">{q}</li>)}</ol>
          {qs.length > 5 && <div className="tiny muted">+{qs.length - 5} more in Requirements</div>}
        </div>
      </div>
    </Section>
  )
}

type Sc = { effort_pct: number; risk_level: string; start_shift_weeks: number; model: string; discount_pct: string; name: string }
const D0: Sc = { effort_pct: 0, risk_level: '', start_shift_weeks: 0, model: '', discount_pct: '', name: '' }
const sign = (n: number) => (n > 0 ? `+${n.toLocaleString()}` : n.toLocaleString())
const tone = (n: number, upIsBad = true) => (n === 0 ? 'delta-zero' : (n > 0) === upIsBad ? 'delta-up' : 'delta-down')

export function Scenarios({ deal, onApplied }: { deal: Deal; onApplied: () => void }) {
  const r: any = deal.results
  const [sc, setSc] = useState<Sc>(D0)
  const [out, setOut] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [saved, setSaved] = useState<any[]>(r.scenarios ?? [])
  const body = () => ({ effort_pct: Number(sc.effort_pct) || 0, risk_level: sc.risk_level || null, start_shift_weeks: Number(sc.start_shift_weeks) || 0,
    model: sc.model || null, discount_pct: sc.discount_pct === '' ? null : Number(sc.discount_pct), name: sc.name })
  useEffect(() => {
    const t = window.setTimeout(() => {
      api.post<any>(`/api/deals/${deal.id}/scenario`, body()).then((o) => { setOut(o); setErr(null) }).catch((e) => setErr(e.message))
    }, 250)
    return () => window.clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sc.effort_pct, sc.risk_level, sc.start_shift_weeks, sc.model, sc.discount_pct, deal.id])
  if (!r.estimate_draft && !r.estimate) return null
  const save = async () => {
    setBusy(true)
    try { const res = await api.post<any>(`/api/deals/${deal.id}/scenarios`, body()); setSaved(res.scenarios) } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  const apply = async () => {
    if (!window.confirm('Apply this scenario? The estimate, team, schedule and price are replaced by the scenario, then the Deal Critic and the Proposal Writer re-run (about a minute). The original is kept for comparison.')) return
    setBusy(true)
    try { await api.post(`/api/deals/${deal.id}/scenarios/apply`, body()); onApplied() } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  const d = out?.delta
  return (
    <Section title="Scenarios: change an assumption, everything downstream is recomputed"
      right={<span className="tiny muted">code only: instant and free · apply re-runs the Critic and Writer</span>}>
      {out?.policy_drift && <div className="notice amber small" style={{ marginBottom: 12 }}>{out.policy_drift.note}</div>}
      <div className="scen-grid">
        <label className="field">Effort <span className="hint">{sc.effort_pct > 0 ? '+' : ''}{sc.effort_pct}%</span>
          <input type="range" min={-30} max={50} step={5} value={sc.effort_pct} onChange={(e) => setSc({ ...sc, effort_pct: Number(e.target.value) })} /></label>
        <label className="field">Risk (contingency)
          <select value={sc.risk_level} onChange={(e) => setSc({ ...sc, risk_level: e.target.value })}>
            <option value="">as estimated ({r.estimate?.risk_level})</option><option value="low">low (10%)</option><option value="medium">medium (15%)</option><option value="high">high (25%)</option>
          </select></label>
        <label className="field">Start <span className="hint">{sc.start_shift_weeks > 0 ? '+' : ''}{sc.start_shift_weeks} weeks</span>
          <input type="range" min={0} max={12} step={1} value={sc.start_shift_weeks} onChange={(e) => setSc({ ...sc, start_shift_weeks: Number(e.target.value) })} /></label>
        <label className="field">Commercial model
          <select value={sc.model} onChange={(e) => setSc({ ...sc, model: e.target.value })}>
            <option value="">as recommended ({r.quote?.recommended_model === 'fixed' ? 'fixed' : 'T&M'})</option><option value="fixed">fixed price</option><option value="tm">time & materials</option>
          </select></label>
        <label className="field">Discount %
          <input type="number" min={0} max={30} step={1} placeholder={`${r.quote?.discount_pct ?? 0}`} value={sc.discount_pct} onChange={(e) => setSc({ ...sc, discount_pct: e.target.value })} /></label>
      </div>
      {err && <div className="notice red small" style={{ marginTop: 10 }}>{err}</div>}
      {out && (
        <table className="tbl" style={{ marginTop: 14 }}>
          <thead><tr><th>Result</th><th className="right">Today's baseline</th><th className="right">This scenario</th><th className="right">Change</th></tr></thead>
          <tbody>
            <tr><td>Hours priced (with contingency)</td><td className="right">{Math.round(out.baseline.estimate.total_hours).toLocaleString()}</td><td className="right">{Math.round(out.estimate.total_hours).toLocaleString()}</td><td className={`right ${tone(d.hours)}`}>{sign(Math.round(d.hours))} h</td></tr>
            <tr><td>Go-live (team re-planned from real availability)</td><td className="right">{fmtDate(out.baseline.schedule.go_live)}</td><td className="right">{fmtDate(out.schedule.go_live)}{out.schedule.meets_deadline === false ? ' · late' : ''}</td><td className={`right ${tone(d.go_live_days)}`}>{sign(d.go_live_days)} days</td></tr>
            <tr><td>Price ({out.price.model === 'fixed' ? 'fixed' : 'T&M'}{out.price.discount_pct ? `, ${out.price.discount_pct}% off` : ''})</td><td className="right">{fmtMoney(out.price.currency, out.baseline.price.price)}</td><td className="right">{fmtMoney(out.price.currency, out.price.price)}</td><td className={`right ${tone(d.price, false)}`}>{sign(d.price)}</td></tr>
            <tr><td>Margin (internal)</td><td className="right">{out.baseline.price.margin_pct}%</td><td className="right">{out.price.margin_pct}%</td><td className={`right ${tone(d.margin_pts, false)}`}>{sign(d.margin_pts)} pts</td></tr>
            <tr><td>Policy</td><td /><td className="right" colSpan={2}>{out.price.needs_approval ? <span className="sev amber">needs a Director: {out.price.approval_reasons.join('; ')}</span> : <span className="sev green">within policy</span>}</td></tr>
            {out.phase1 && <tr><td>Phase 1 option</td><td /><td className="right" colSpan={2}>{fmtMoney(out.price.currency, out.phase1.price_fixed)} fixed · go-live {fmtDate(out.phase1.go_live)}</td></tr>}
          </tbody>
        </table>
      )}
      <div className="row" style={{ marginTop: 12 }}>
        <input placeholder="Name this scenario (optional)" value={sc.name} onChange={(e) => setSc({ ...sc, name: e.target.value })} style={{ maxWidth: 280 }} />
        <button className="btn" disabled={busy} onClick={save}><Save size={14} /> Save to compare</button>
        <button className="btn btn-primary" disabled={busy || deal.status === 'approved'} onClick={apply}><Play size={14} /> Apply and re-run review</button>
        <button className="btn btn-ghost" onClick={() => setSc(D0)}>Reset</button>
      </div>
      {saved.length > 0 && (
        <table className="tbl" style={{ marginTop: 14 }}>
          <thead><tr><th>Saved scenario</th><th className="right">Hours</th><th className="right">Go-live</th><th className="right">Price</th><th className="right">Margin</th><th>Policy</th></tr></thead>
          <tbody>{saved.map((s: any, i: number) => (
            <tr key={i}><td className="small"><b>{s.name}</b><div className="tiny muted">{s.by} · effort {s.params.effort_pct}% · start +{s.params.start_shift_weeks}w{s.params.discount_pct != null ? ` · ${s.params.discount_pct}% off` : ''}</div></td>
              <td className="right">{Math.round(s.estimate.total_hours).toLocaleString()}</td><td className="right">{fmtDate(s.schedule.go_live)}</td>
              <td className="right">{fmtMoney(s.price.currency, s.price.price)}</td><td className="right">{s.price.margin_pct}%</td>
              <td>{s.price.needs_approval ? <span className="sev amber">Director</span> : <span className="sev green">OK</span>}</td></tr>
          ))}</tbody>
        </table>
      )}
      {r.applied_scenario && <div className="tiny muted" style={{ marginTop: 8 }}>Applied by {r.applied_scenario.by} on {fmtDate(r.applied_scenario.at)}; the agents' original numbers are kept for comparison.</div>}
    </Section>
  )
}

const FLOW_ICON: Record<string, typeof Check> = { agent_end: Check, handoff: ArrowRightLeft, calculator: Calculator, finding: Flag, status: UserCheck }

export function Collaboration({ deal }: { deal: Deal }) {
  const [c, setC] = useState<any>(null)
  useEffect(() => { api.get<any>(`/api/activity/${deal.id}`).then(setC).catch(() => setC(null)) }, [deal.id, deal.status])
  const findings: any[] = (deal.results as any).findings ?? []
  return (
    <div className="grid g2" style={{ alignItems: 'start' }}>
      <Section title="How the agents collaborated on this deal">
        {!c && <div className="empty"><span className="spinner" /></div>}
        <div className="flow">{(c?.collaboration ?? []).map((f: any, i: number) => {
          const I = FLOW_ICON[f.kind] ?? Check
          return <div key={i} className={`flow-item ${f.kind}`}><span className="flow-dot"><I size={11} strokeWidth={2.6} /></span><span className="flow-who">{f.label}</span><span className="flow-text">{f.text}</span></div>
        })}</div>
        <div className="tiny muted" style={{ marginTop: 10 }}>✓ agent finished · ⇄ work sent back · ⌗ number computed by code · ⚑ finding posted to the shared board</div>
      </Section>
      <Section title={`Shared findings board (${findings.length})`}>
        {findings.length === 0 && <div className="small muted">No conflicts were posted for this deal{(deal as any).revisions ? '; the Deal Critic\'s send-backs show in the timeline.' : '.'} Deals created before the orchestrator was added show their hand-offs in the timeline only.</div>}
        <div className="col" style={{ gap: 10 }}>{findings.map((f, i) => (
          <div key={i} className="small"><b>{f.from} → {f.to}</b> <span className={`sev ${f.severity === 'high' ? 'red' : f.severity === 'warning' ? 'amber' : 'neutral'}`}>{f.kind}</span>{f.pass > 1 && <span className="tiny muted"> · after re-run {f.pass - 1}</span>}
            <div>{f.finding}</div><div className="tiny muted">Evidence: {f.evidence}</div><div className="tiny muted">Action: {f.action}</div></div>
        ))}</div>
      </Section>
    </div>
  )
}
