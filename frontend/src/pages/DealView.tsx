import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { ArrowLeft, BadgeDollarSign, Blocks, Calculator, Check, Code2, Filter, LoaderCircle, Minus, PenLine, ScanSearch, ShieldAlert, ShieldCheck, Swords, TriangleAlert, Users, X } from 'lucide-react'
import DealRoom from './DealRoom'
import { Blockers, Collaboration, Scenarios, StageBar } from './DealWorkspace'
import { useHashParams } from '../lib'
import { Confetti, HealthRing } from '../fun'
import { api } from '../api'
import {
  Bar,
  List,
  Pill,
  ROLE_LABEL,
  Section,
  Stat,
  StatusPill,
  fmtDate,
  fmtDateTime,
  fmtInt,
  fmtK,
  fmtMoney,
  fmtUsd,
  sevTone,
} from '../lib'
import { Markdown, markdownToHtml } from '../markdown'
import type { Deal, Step, TraceEvent } from '../types'

const TABS = [
  'Overview',
  'Requirements',
  'Feasibility',
  'Staffing',
  'Pricing',
  'Proposal',
  'Deal Room',
  'Collaboration',
  'Internal memo',
  'Agent trace',
  'Tokens & cost',
] as const
type Tab = (typeof TABS)[number]

const PARALLEL = new Set<string>()  // staffing and pricing now run in sequence (pricing reads the schedule)

export default function DealView({ id }: { id: string }) {
  const [deal, setDeal] = useState<Deal | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const params = useHashParams()
  const [tab, setTab] = useState<Tab>(params.tab === 'room' ? 'Deal Room' : 'Overview')
  const [reload, setReload] = useState(0)
  const [traceAgent, setTraceAgent] = useState<string>('all')

  useEffect(() => {
    let stop = false
    let timer: number | undefined
    const load = async () => {
      try {
        const d = await api.get<Deal>(`/api/deals/${id}`)
        if (stop) return
        setDeal(d)
        if (d.status === 'running' || d.status === 'queued') timer = window.setTimeout(load, 1200)
      } catch (e) {
        if (!stop) setErr((e as Error).message)
      }
    }
    load()
    return () => {
      stop = true
      if (timer) window.clearTimeout(timer)
    }
  }, [id, reload])

  if (err) return <div className="page"><div className="notice red">{err}</div></div>
  if (!deal) return <div className="page"><div className="empty"><span className="spinner" /></div></div>

  const r = deal.results
  const steps = Object.values(deal.steps)
  const running = deal.status === 'running' || deal.status === 'queued'
  const highScreen = deal.screen?.findings?.filter((f) => f.severity === 'high') ?? []
  const u = deal.usage

  const openTrace = (key: string) => {
    setTraceAgent(key)
    setTab('Agent trace')
  }

  const focus = steps.find((s) => s.status === 'running') ?? [...steps].reverse().find((s) => s.status === 'done' || s.status === 'failed')
  return (
    <div className="page">
      <div className="page-head">
        <div style={{ flex: 1, minWidth: 0 }}>
          <a href="#/deals" className="small muted row" style={{ gap: 4 }}><ArrowLeft size={14} /> All deals</a>
          <h1 style={{ marginTop: 8 }}>{deal.title}</h1>
          <div className="meta-line">
            <StatusPill status={deal.status} />
            <span>Started <b>{fmtDateTime(deal.created_at)}</b>{deal.input.created_by ? <> by <b>{deal.input.created_by}</b></> : null}</span>
            {u && <span><b>{fmtK(u.input_tokens + u.output_tokens)}</b> tokens · <b>{fmtUsd(u.cost_usd)}</b></span>}
            <span className="mono">{deal.model}</span>
            {deal.revisions > 0 && <Pill tone="violet">critic sent work back {deal.revisions}×</Pill>}
            {deal.demo && <Pill tone="blue">example from a real run</Pill>}
          </div>
        </div>
      </div>

      <div className="card card-pad">
        <div className="stepper">
          {steps.map((s) => (
            <StepDot key={s.key} s={s} onClick={() => openTrace(s.key)} />
          ))}
        </div>
        {focus?.summary && (
          <div className="step-summary">
            {running ? <LoaderCircle size={15} className="spin" /> : <Check size={15} color="var(--green-2)" />}
            <span><b>{focus.label}:</b> {focus.summary}</span>
            <span className="spacer" />
            <button className="btn btn-ghost btn-sm" onClick={() => openTrace(focus.key)}>View trace</button>
          </div>
        )}
      </div>

      {deal.status === 'failed' && <div className="notice red">Run failed: {deal.error}</div>}
      {running && (
        <div className="notice blue small">
          <LoaderCircle size={16} className="spin" /> The agents are working. This page updates live; a full run takes about 2–3 minutes.
        </div>
      )}
      {highScreen.length > 0 && (
        <div className="notice amber small">
          <TriangleAlert size={16} color="var(--amber)" />
          <div>
            <b>Prompt-injection attempt detected in the client document and neutralised.</b> Hidden or AI-directed instructions were
            removed or treated as data; prices and margins are computed by code, and the proposal passed the leak guard.
            <div className="muted tiny" style={{ marginTop: 4 }}>
              {highScreen.map((f, i) => (
                <div key={i}>• {f.message} {f.snippet && <span className="mono">“{f.snippet}”</span>}</div>
              ))}
            </div>
          </div>
        </div>
      )}

      <StageBar deal={deal} tab={tab} setTab={setTab} />

      <div className="tabs no-print">
        {TABS.map((t) => (
          <div key={t} className={`tab ${tab === t ? 'active' : ''}`} onClick={() => setTab(t)}>
            {t}
            {t === 'Deal Room' && <Swords size={13} style={{ marginLeft: 5, verticalAlign: -2 }} />}
            {t === 'Agent trace' && <span className="count">{deal.trace.length}</span>}
          </div>
        ))}
      </div>

      <div key={tab} className="tab-anim">
        {tab === 'Overview' && <Overview deal={deal} />}
        {tab === 'Requirements' && <Requirements deal={deal} />}
        {tab === 'Feasibility' && <div className="col" style={{ gap: 16 }}><Solution deal={deal} /><EstimateTab deal={deal} /></div>}
        {tab === 'Staffing' && <TeamTab deal={deal} />}
        {tab === 'Pricing' && <div className="col" style={{ gap: 16 }}><PricingTab deal={deal} />{!running && deal.results.quote && <Scenarios deal={deal} onApplied={() => setReload((n) => n + 1)} />}</div>}
        {tab === 'Proposal' && <div className="col" style={{ gap: 16 }}><ReviewTab deal={deal} /><ProposalTab deal={deal} /></div>}
        {tab === 'Collaboration' && <Collaboration deal={deal} />}
        {tab === 'Deal Room' && (deal.results.quote && !running ? <DealRoom deal={deal} /> : <Pending />)}
        {tab === 'Internal memo' && (r.memo_markdown ? <Markdown text={r.memo_markdown} dark /> : <Pending />)}
        {tab === 'Agent trace' && <Trace events={deal.trace} agent={traceAgent} setAgent={setTraceAgent} steps={steps} />}
        {tab === 'Tokens & cost' && <UsageTab deal={deal} />}
      </div>

      {['ready', 'approved', 'rejected', 'changes_requested'].includes(deal.status) && (
        <DecisionBar deal={deal} onDone={(d) => setDeal(d)} />
      )}
    </div>
  )
}

const AGENT_ICON: Record<string, typeof Check> = {
  screen: Filter, analyst: ScanSearch, architect: Blocks, estimator: Calculator, staffing: Users,
  pricing: BadgeDollarSign, critic: ShieldAlert, writer: PenLine, guard: ShieldCheck,
}

function StepDot({ s, onClick }: { s: Step; onClick: () => void }) {
  const Glyph = AGENT_ICON[s.key] ?? Code2
  const icon =
    s.status === 'done' ? <Check size={16} strokeWidth={2.6} /> :
    s.status === 'failed' ? <X size={16} strokeWidth={2.6} /> :
    s.status === 'running' ? <Glyph size={15} /> :
    s.status === 'skipped' ? <Minus size={16} /> : <Glyph size={15} />
  const meta = s.status === 'running' ? 'working…' : s.seconds != null ? `${s.seconds}s${s.usage ? ` · ${fmtUsd(s.usage.cost_usd, 4)}` : ''}` : ''
  return (
    <div className={`step ${s.status} ${s.kind === 'code' ? 'code' : ''}`} onClick={onClick} title={[s.job, s.summary].filter(Boolean).join('\n\n')}>
      {(s.rounds ?? 0) > 1 && <span className="rounds">×{s.rounds}</span>}
      <div className="step-dot">{icon}{s.status === 'done' && <span className="step-glyph"><Glyph size={10} /></span>}</div>
      <div className="step-label">{s.label}{PARALLEL.has(s.key) ? ' ∥' : ''}</div>
      <div className="step-meta">{meta}</div>
    </div>
  )
}

const Pending = () => <div className="card empty">This part appears when the agents get there.</div>

// ------------------------------------------------------------------ Overview

function Overview({ deal }: { deal: Deal }) {
  const { spec, design, estimate: est, schedule: sch, quote: q, review, phase1 } = deal.results
  if (!spec) return <Pending />
  const rec = q?.options.find((o) => o.model === q.recommended_model)
  const margin = q ? (q.recommended_model === 'fixed' ? q.margin_pct_fixed : q.margin_pct_tm) : null
  return (
    <div className="col" style={{ gap: 16 }}>
      {q && sch && review && <HealthRing deal={deal} />}
      <Blockers deal={deal} />
      <div className="grid g4">
        <Stat label="Expected effort" value={est ? `${fmtInt(est.expected_hours ?? est.total_hours)} h` : '…'} foot={est ? `${fmtInt(est.total_hours)} h priced with ${est.contingency_pct}% contingency · ${est.risk_level} risk` : ''} />
        <Stat
          label="Timeline"
          value={sch ? `${sch.total_weeks} wks` : '…'}
          foot={sch ? (
            <>go-live {fmtDate(sch.end_date)}{sch.meets_deadline === false && <span className="red"> · misses deadline</span>}{sch.meets_deadline && <span className="green"> · meets deadline</span>}</>
          ) : ''}
        />
        <Stat
          label={`Recommended: ${q ? (q.recommended_model === 'fixed' ? 'fixed price' : 'time & materials') : '…'}`}
          value={rec ? fmtMoney(rec.currency, rec.price) : '…'}
          foot={q?.budget_fit ?? (q ? 'Client gave no budget' : '')}
        />
        <Stat
          label="Margin (internal)"
          value={margin != null ? `${margin.toFixed(1)}%` : '…'}
          foot={q ? <>floor {q.margin_floor_pct}% · target {q.target_margin_pct}%{q.needs_approval && <span className="amber"> · needs approval</span>}</> : ''}
        />
      </div>

      <div className="grid g2">
        <Section title="What the client wants" right={<span className="pill">{spec.project_type}</span>}>
          <p>{spec.summary}</p>
          <div className="row" style={{ marginTop: 10 }}>
            {spec.compliance_flags.map((c) => <Pill key={c} tone="blue">{c}</Pill>)}
            {spec.existing_client && <Pill tone="green">Existing client</Pill>}
            {spec.constraints.deadline && <Pill tone="amber">Deadline: {spec.constraints.deadline}</Pill>}
            {spec.constraints.budget_text && <Pill tone="amber">Budget: {spec.constraints.budget_text}</Pill>}
          </div>
        </Section>
        <Section
          title="Deal Critic's recommendation"
          right={review ? <Pill tone={review.verdict === 'approve' ? 'green' : review.verdict === 'revise' ? 'violet' : 'amber'}>{review.verdict}</Pill> : null}
        >
          {review ? <p>{review.go_no_go}</p> : <div className="muted">Waiting for the review…</div>}
        </Section>
      </div>

      {phase1 && q && (
        <div className="notice green">
          <span>◆</span>
          <div className="small">
            <b>Phased option ready for the budget conversation:</b> Phase 1 ({phase1.packages.join(', ')}) for{' '}
            <b>{fmtMoney(q.currency, phase1.fixed_price)}</b> fixed, {fmtInt(phase1.hours)} h, go-live {fmtDate(phase1.go_live)}.{' '}
            {phase1.budget_fit} Phase 2 later: {phase1.later_packages.join(', ')}.
          </div>
        </div>
      )}

      <div className="grid g3">
        <Section title="Feasibility" right={design ? <Pill tone={design.feasibility === 'feasible' ? 'green' : design.feasibility === 'not_recommended' ? 'red' : 'amber'}>{design.feasibility.replace(/_/g, ' ')}</Pill> : null}>
          <List items={design?.feasibility_reasons} />
        </Section>
        <Section title="Top risks">
          <List items={design?.risks.slice(0, 4).map((x) => `${x.risk} (${x.impact})`)} />
        </Section>
        <Section title="Ask the client first">
          <List items={spec.open_questions.slice(0, 5)} />
        </Section>
      </div>

      {q?.needs_approval && (
        <div className="notice amber small">
          <b>Needs management approval:</b>&nbsp;{q.approval_reasons.join(' ')}
        </div>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ Requirements

function Requirements({ deal }: { deal: Deal }) {
  const s = deal.results.spec
  if (!s) return <Pending />
  const c = s.constraints
  return (
    <div className="col" style={{ gap: 16 }}>
      <Section title={`${s.project_title} · ${s.client_name} (${s.client_country}, ${s.industry})`}>
        <p>{s.summary}</p>
        {s.client_history && <div className="notice small" style={{ marginTop: 10 }}>Client history: {s.client_history}</div>}
      </Section>
      <Section title={`Features (${s.features.length})`}>
        <table className="tbl">
          <thead><tr><th>Feature</th><th>Priority</th><th>Module</th><th>Description</th></tr></thead>
          <tbody>
            {s.features.map((f, i) => (
              <tr key={i}>
                <td className="strong">{f.name}</td>
                <td><Pill tone={f.priority === 'must' ? 'green' : f.priority === 'should' ? 'blue' : ''}>{f.priority}</Pill></td>
                <td className="mono muted">{f.module_key ?? '–'}</td>
                <td className="muted">{f.description}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <div className="grid g3">
        <Section title="Constraints">
          <dl className="kv">
            <dt>Deadline</dt><dd>{c.deadline ?? '–'} {c.deadline_date && <span className="muted">({fmtDate(c.deadline_date)})</span>}</dd>
            <dt>Wants to start</dt><dd>{c.requested_start ? fmtDate(c.requested_start) : '–'}</dd>
            <dt>Budget</dt><dd>{c.budget_text ?? '–'}</dd>
            <dt>Stack</dt><dd>{c.preferred_stack.join(', ') || '–'}</dd>
            <dt>Languages</dt><dd>{c.languages.join(', ') || '–'}</dd>
            <dt>Platforms</dt><dd>{s.platforms.join(', ')}</dd>
          </dl>
          {c.other.length > 0 && <div style={{ marginTop: 8 }}><List items={c.other} /></div>}
        </Section>
        <Section title="Integrations & non-functional">
          <List items={[...s.integrations.map((x) => `Integration: ${x}`), ...s.non_functional]} />
        </Section>
        <Section title="Compliance">
          <div className="row">{s.compliance_flags.map((x) => <Pill key={x} tone="blue">{x}</Pill>)}</div>
          {s.compliance_flags.length === 0 && <div className="muted small">None identified</div>}
        </Section>
      </div>
      <div className="grid g2">
        <Section title="Open questions for the client"><List items={s.open_questions} /></Section>
        <Section title="Assumptions if they don't answer"><List items={s.assumptions} /></Section>
      </div>
      {s.suspicious_content.length > 0 && (
        <div className="notice amber small">
          <b>Analyst flagged text aimed at the AI:</b>&nbsp;{s.suspicious_content.join(' · ')}
        </div>
      )}
      <Section title="Original request (after the safety screen)">
        <pre className="trace-data" style={{ maxHeight: 360 }}>{deal.input.brief}</pre>
      </Section>
    </div>
  )
}

// ------------------------------------------------------------------ Solution

function Solution({ deal }: { deal: Deal }) {
  const d = deal.results.design
  if (!d) return <Pending />
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="grid g2">
        <Section title="Feasibility" right={<Pill tone={d.feasibility === 'feasible' ? 'green' : d.feasibility === 'not_recommended' ? 'red' : 'amber'}>{d.feasibility.replace(/_/g, ' ')}</Pill>}>
          <List items={d.feasibility_reasons} />
        </Section>
        <Section title="Capability gaps at Empower">
          <List items={d.capability_gaps} empty="No gaps: Empower has the skills in-house." />
          {d.reference_projects.length > 0 && (
            <div className="small muted" style={{ marginTop: 10 }}>Similar past projects: <span className="mono">{d.reference_projects.join(', ')}</span></div>
          )}
        </Section>
      </div>
      <Section title="Recommended stack">
        <table className="tbl">
          <thead><tr><th>Layer</th><th>Technology</th><th>Why</th></tr></thead>
          <tbody>{d.recommended_stack.map((s, i) => <tr key={i}><td className="strong">{s.layer}</td><td>{s.technology}</td><td className="muted">{s.reason}</td></tr>)}</tbody>
        </table>
      </Section>
      <Section title={`Work packages (${d.work_packages.length})`}>
        <table className="tbl">
          <thead><tr><th>Package</th><th>Priority</th><th>Complexity</th><th>Module</th><th>Scope</th></tr></thead>
          <tbody>
            {d.work_packages.map((w, i) => (
              <tr key={i}>
                <td className="strong">{w.name}</td>
                <td><Pill tone={w.priority === 'must' ? 'green' : 'blue'}>{w.priority}</Pill></td>
                <td><Pill tone={w.complexity === 'high' ? 'amber' : ''}>{w.complexity}</Pill></td>
                <td className="mono muted">{w.module_key}</td>
                <td className="muted">{w.scope_notes}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Risks">
        <table className="tbl">
          <thead><tr><th>Risk</th><th>Impact</th><th>Mitigation</th></tr></thead>
          <tbody>{d.risks.map((x, i) => <tr key={i}><td>{x.risk}</td><td><Pill tone={sevTone(x.impact)}>{x.impact}</Pill></td><td className="muted">{x.mitigation}</td></tr>)}</tbody>
        </table>
      </Section>
    </div>
  )
}

// ------------------------------------------------------------------ Estimate

function EstimateTab({ deal }: { deal: Deal }) {
  const e = deal.results.estimate
  if (!e) return <Pending />
  const roles = Object.entries(e.hours_by_role).sort((a, b) => b[1] - a[1])
  const max = roles[0]?.[1] ?? 1
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="grid g4">
        <Stat label="Expected effort" value={`${fmtInt(e.expected_hours ?? e.total_hours)} h`} foot={`likely ${fmtInt(e.low_hours)}–${fmtInt(e.high_hours)} h · priced at ${fmtInt(e.total_hours)} h`} />
        <Stat label="Build (agent estimate)" value={`${fmtInt(e.build_hours)} h`} foot={e.qa_topup_hours > 0 ? `+${fmtInt(e.qa_topup_hours)} h QA top-up by policy` : 'QA meets the 20% policy'} />
        <Stat label="PM + tech lead (policy)" value={`${fmtInt(e.pm_hours + e.lead_hours)} h`} foot="10% PM + 6% lead, added in code" />
        <Stat label={`Contingency (${e.risk_level} risk)`} value={`${e.contingency_pct}%`} foot={`${fmtInt(e.contingency_hours)} h`} />
      </div>
      {e.historical_underestimate_pct != null && (
        <div className="notice blue small">
          <span>ℹ</span>
          <div>
            Empower's past estimates for <b>{deal.results.spec?.project_type}</b> projects came in <b>{e.historical_underestimate_pct.toFixed(0)}% under</b> the
            hours actually worked. This estimate is built from <b>actual</b> hours of similar modules, so it already corrects for that.
          </div>
        </div>
      )}
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) minmax(0,1.6fr)' }}>
        <Section title="Hours by role">
          <div className="col" style={{ gap: 8 }}>
            {roles.map(([role, h]) => (
              <div className="bar-row" key={role}>
                <span>{ROLE_LABEL[role] ?? role}</span>
                <Bar value={h} max={max} tone={role === 'pm' || role === 'lead' ? 'blue' : undefined} />
                <span className="mono right">{fmtInt(h)} h</span>
              </div>
            ))}
          </div>
        </Section>
        <Section title="Line items vs Empower's history">
          <table className="tbl">
            <thead><tr><th>Package</th><th className="num">Hours</th><th className="num">History</th><th className="num">Δ</th><th>Basis</th></tr></thead>
            <tbody>
              {e.lines.map((l, i) => (
                <tr key={i}>
                  <td><div className="strong">{l.work_package}</div><div className="tiny muted mono">{l.module_key} · {l.complexity}</div></td>
                  <td className="num">{fmtInt(l.total_hours)}</td>
                  <td className="num muted">{l.benchmark_hours != null ? fmtInt(l.benchmark_hours) : '–'}</td>
                  <td className={`num ${l.deviation_pct != null && Math.abs(l.deviation_pct) > 40 ? 'amber' : 'muted'}`}>
                    {l.deviation_pct != null ? `${l.deviation_pct > 0 ? '+' : ''}${l.deviation_pct.toFixed(0)}%` : '–'}
                  </td>
                  <td className="small muted">
                    {l.basis}
                    {l.reference_projects.length > 0 && <span className="mono"> [{l.reference_projects.join(', ')}]</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      </div>
      {e.warnings.length > 0 && <Section title="Calculator checks"><List items={e.warnings} /></Section>}
    </div>
  )
}

// ------------------------------------------------------------------ Team & timeline

function TeamTab({ deal }: { deal: Deal }) {
  const s = deal.results.schedule
  if (!s) return <Pending />
  const total = Math.max(s.total_weeks, 1)
  const pct = (w: number) => `${(100 * w) / total}%`
  const roleRows = Object.entries(s.role_weeks).sort((a, b) => b[1] - a[1])
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="grid g4">
        <Stat label="Start" value={fmtDate(s.start_date)} small />
        <Stat label="Go-live" value={fmtDate(s.end_date)} small foot={s.meets_deadline === false ? <span className="red">after the client's deadline</span> : s.meets_deadline ? <span className="green">meets the deadline</span> : 'no deadline given'} />
        <Stat label="Duration" value={`${s.total_weeks} weeks`} small foot={`bottleneck: ${s.bottleneck_role ? ROLE_LABEL[s.bottleneck_role] ?? s.bottleneck_role : '–'}`} />
        <Stat label="Team" value={`${s.team.length} people`} small foot={s.uncovered_roles.length ? <span className="amber">{s.uncovered_roles.length} role(s) to hire</span> : 'all roles covered'} />
      </div>
      <Section title="Timeline">
        <div className="gantt">
          <div className="gantt-row">
            <span className="strong">Discovery & design</span>
            <div className="gantt-track"><div className="gantt-bar phase" style={{ left: 0, width: pct(s.discovery_weeks) }}>{s.discovery_weeks}w</div></div>
          </div>
          <div className="gantt-row">
            <span className="strong">Build & test</span>
            <div className="gantt-track"><div className="gantt-bar" style={{ left: pct(s.discovery_weeks), width: pct(s.build_weeks) }}>{s.build_weeks}w</div></div>
          </div>
          {roleRows.map(([role, w]) => (
            <div className="gantt-row" key={role}>
              <span className="muted small" style={{ paddingLeft: 12 }}>{ROLE_LABEL[role] ?? role}</span>
              <div className="gantt-track">
                <div className={`gantt-bar ${s.uncovered_roles.includes(role) ? 'hire' : ''}`} style={{ left: pct(s.discovery_weeks), width: pct(w), opacity: 0.85 }}>
                  {w}w{s.uncovered_roles.includes(role) ? ' (hire)' : ''}
                </div>
              </div>
            </div>
          ))}
          <div className="gantt-row">
            <span className="strong">UAT & stabilisation</span>
            <div className="gantt-track"><div className="gantt-bar stab" style={{ left: pct(s.discovery_weeks + s.build_weeks), width: pct(s.stabilization_weeks) }}>{s.stabilization_weeks}w</div></div>
          </div>
        </div>
      </Section>
      <Section title="Proposed team (from people actually free in the window)">
        <table className="tbl">
          <thead><tr><th>Person</th><th>Role on project</th><th>Office</th><th className="num">Allocation</th><th className="num">Free in window</th><th>Check</th></tr></thead>
          <tbody>
            {s.team.map((m) => (
              <tr key={m.emp_id}>
                <td><div className="strong">{m.name}</div><div className="tiny muted">{m.title} · <span className="mono">{m.emp_id}</span></div></td>
                <td>{ROLE_LABEL[m.role] ?? m.role}</td>
                <td>{m.office}</td>
                <td className="num">{m.allocation_pct}%</td>
                <td className="num">{m.free_pct}%</td>
                <td>{m.conflict ? <Pill tone="red">{m.conflict}</Pill> : <Pill tone="green">available</Pill>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <div className="grid g2">
        <Section title="Gaps to fill (hire / contract)"><List items={[...s.gaps, ...s.uncovered_roles.map((r) => `No one free for ${ROLE_LABEL[r] ?? r}`)]} empty="None" /></Section>
        <Section title="Schedule checks"><List items={s.warnings} empty="No conflicts." /></Section>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Pricing

function PricingTab({ deal }: { deal: Deal }) {
  const { quote: q, pricing_decision: pd, phase1 } = deal.results
  if (!q || !pd) return <Pending />
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="grid g3">
        {q.options.map((o) => (
          <div className="card card-pad col" key={o.model} style={{ borderColor: o.model === q.recommended_model ? 'var(--accent)' : undefined }}>
            <div className="row">
              <h3>{o.label}</h3>
              {o.model === q.recommended_model && <Pill tone="green">recommended</Pill>}
            </div>
            <div className="mono" style={{ fontSize: 26, fontWeight: 700 }}>{fmtMoney(o.currency, o.price)}</div>
            <div className="small muted">
              {fmtInt(o.hours)} h · blended {o.currency} {o.blended_rate.toFixed(2)}/h
              {o.monthly_estimate ? ` · ~${fmtMoney(o.currency, o.monthly_estimate)}/month` : ''}
            </div>
            <div className="small">{o.terms}</div>
          </div>
        ))}
        {phase1 ? (
          <div className="card card-pad col">
            <div className="row"><h3>Phase 1 only</h3><Pill tone="violet">budget option</Pill></div>
            <div className="mono" style={{ fontSize: 26, fontWeight: 700 }}>{fmtMoney(q.currency, phase1.fixed_price)}</div>
            <div className="small muted">{fmtInt(phase1.hours)} h ({phase1.share_of_full_scope_pct}% of scope) · go-live {fmtDate(phase1.go_live)}</div>
            <div className="small">{phase1.budget_fit}</div>
            <div className="tiny muted">Later: {phase1.later_packages.join(', ')}</div>
          </div>
        ) : (
          <div className="card card-pad muted small">No phased option: every work package is a must-have.</div>
        )}
      </div>

      <div className="grid g2">
        <Section title="Internal economics (never shown to the client)">
          <dl className="kv">
            <dt>Delivery cost</dt><dd className="mono">{fmtMoney(q.currency, q.internal_cost)}</dd>
            <dt>Margin, fixed</dt><dd className="mono">{q.margin_pct_fixed.toFixed(1)}%</dd>
            <dt>Margin, T&M</dt><dd className="mono">{q.margin_pct_tm.toFixed(1)}%</dd>
            <dt>Floor / target</dt><dd className="mono">{q.margin_floor_pct}% / {q.target_margin_pct}%</dd>
            <dt>Discount</dt><dd className="mono">{q.discount_pct}%</dd>
            <dt>Budget fit</dt><dd>{q.budget_fit ?? 'No budget given'}</dd>
          </dl>
          <div className="col" style={{ gap: 6, marginTop: 12 }}>
            {[['Fixed', q.margin_pct_fixed], ['T&M', q.margin_pct_tm]].map(([l, m]) => (
              <div className="bar-row" key={l as string}>
                <span>{l} margin</span>
                <Bar value={m as number} max={80} tone={(m as number) < q.margin_floor_pct ? 'amber' : undefined} />
                <span className="mono right">{(m as number).toFixed(1)}%</span>
              </div>
            ))}
          </div>
          {q.needs_approval ? (
            <div className="notice amber small" style={{ marginTop: 10 }}>Needs approval: {q.approval_reasons.join(' ')}</div>
          ) : (
            <div className="notice green small" style={{ marginTop: 10 }}>Within pricing policy.</div>
          )}
        </Section>
        <Section title="Pricing Strategist's reasoning">
          <List items={pd.rationale} />
          <div className="divider" style={{ margin: '12px 0' }} />
          <div className="strong small" style={{ marginBottom: 6 }}>Negotiation notes (internal)</div>
          <List items={pd.negotiation_notes} />
        </Section>
      </div>

      <div className="grid g2">
        <Section title="Fixed-price milestones">
          <table className="tbl">
            <thead><tr><th>Milestone</th><th className="num">Share</th><th className="num">Amount</th></tr></thead>
            <tbody>{q.options[0].milestones.map((m, i) => <tr key={i}><td>{m.milestone}</td><td className="num">{m.pct}%</td><td className="num">{fmtMoney(q.currency, m.amount)}</td></tr>)}</tbody>
          </table>
        </Section>
        <Section title={`Rate card (${q.currency}/hour)`}>
          <table className="tbl">
            <tbody>
              {Object.entries(q.rate_card).map(([r, v]) => <tr key={r}><td>{ROLE_LABEL[r] ?? r}</td><td className="num">{v}</td></tr>)}
            </tbody>
          </table>
        </Section>
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Review

function ReviewTab({ deal }: { deal: Deal }) {
  const reviews = deal.results.reviews ?? (deal.results.review ? [deal.results.review] : [])
  if (!reviews.length) return <Pending />
  return (
    <div className="col" style={{ gap: 16 }}>
      {reviews.map((rv, idx) => (
        <Section
          key={idx}
          title={`Review round ${idx + 1}${idx === reviews.length - 1 ? ' (final)' : ''}`}
          right={<Pill tone={rv.verdict === 'approve' ? 'green' : rv.verdict === 'revise' ? 'violet' : 'amber'}>{rv.verdict}</Pill>}
        >
          <p>{rv.go_no_go}</p>
          <table className="tbl" style={{ marginTop: 12 }}>
            <thead><tr><th>Severity</th><th>Area</th><th>Finding</th><th>Recommendation</th><th>Sent to</th></tr></thead>
            <tbody>
              {rv.issues.map((i, k) => (
                <tr key={k}>
                  <td><Pill tone={sevTone(i.severity)}>{i.severity}</Pill></td>
                  <td className="small">{i.area}</td>
                  <td className="small">{i.finding}</td>
                  <td className="small muted">{i.recommendation}</td>
                  <td className="small mono">{i.send_back_to}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {rv.strengths.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="strong small" style={{ marginBottom: 4 }}>Strengths</div>
              <List items={rv.strengths} />
            </div>
          )}
        </Section>
      ))}
    </div>
  )
}

// ------------------------------------------------------------------ Proposal

function download(name: string, text: string, type: string) {
  const blob = new Blob([text], { type })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  URL.revokeObjectURL(a.href)
}

function ProposalTab({ deal }: { deal: Deal }) {
  const md = deal.results.proposal_markdown
  const [copied, setCopied] = useState(false)
  if (!md) return <Pending />
  const base = (deal.results.spec?.client_name ?? 'proposal').replace(/[^a-z0-9]+/gi, '-').toLowerCase()
  const leaks = deal.results.leak_findings ?? []
  return (
    <div className="col" style={{ gap: 14 }}>
      <div className="row no-print">
        <button className="btn btn-sm" onClick={() => { navigator.clipboard.writeText(md); setCopied(true); setTimeout(() => setCopied(false), 1500) }}>
          {copied ? '✓ Copied' : 'Copy Markdown'}
        </button>
        <button className="btn btn-sm" onClick={() => download(`${base}-proposal.md`, md, 'text/markdown')}>Download .md</button>
        <button className="btn btn-sm" onClick={() => download(`${base}-proposal.html`, markdownToHtml(md, deal.title), 'text/html')}>Download .html (print to PDF)</button>
        <span className="spacer" />
        {leaks.length ? <Pill tone="red">Leak guard redacted {leaks.length} line(s)</Pill> : <Pill tone="green">Leak guard: clean</Pill>}
        <span className="muted small">Draft only. Nothing has been sent to the client.</span>
      </div>
      {leaks.length > 0 && (
        <div className="notice red small">
          <div>
            <b>The leak guard removed internal information from this draft.</b>
            {leaks.map((f, i) => <div key={i} className="tiny">• {f.message} <span className="mono">“{f.snippet}”</span></div>)}
          </div>
        </div>
      )}
      <Markdown text={md} />
    </div>
  )
}

// ------------------------------------------------------------------ Trace

function preview(data: unknown): string {
  if (data == null) return ''
  if (typeof data === 'string') {
    try {
      return JSON.stringify(JSON.parse(data), null, 1)
    } catch {
      return data
    }
  }
  return JSON.stringify(data, null, 1)
}

function Trace({ events, agent, setAgent, steps }: { events: TraceEvent[]; agent: string; setAgent: (a: string) => void; steps: Step[] }) {
  const [open, setOpen] = useState<Set<number>>(new Set())
  const shown = useMemo(() => events.map((e, i) => ({ e, i })).filter(({ e }) => agent === 'all' || e.agent === agent), [events, agent])
  const label = (k: string) => steps.find((s) => s.key === k)?.label ?? k
  const toggle = (i: number) => setOpen((s) => { const n = new Set(s); if (n.has(i)) n.delete(i); else n.add(i); return n })
  return (
    <div className="card">
      <div className="card-head">
        <h3>Agent trace: every step, tool call and result</h3>
        <div className="row">
          <select value={agent} onChange={(e) => setAgent(e.target.value)} style={{ width: 220 }}>
            <option value="all">All steps ({events.length} events)</option>
            {steps.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
          </select>
        </div>
      </div>
      <div className="trace">
        {shown.map(({ e, i }) => {
          const hasData = e.data != null && e.data !== ''
          return (
            <div className="trace-row" key={i} onClick={() => hasData && toggle(i)} style={{ cursor: hasData ? 'pointer' : 'default' }}>
              <span className="t">+{e.t.toFixed(1)}s</span>
              <span className="who">{label(e.agent)}</span>
              <span className={`trace-kind ${e.kind}`}>{e.kind.replace('_', ' ')}</span>
              <div>
                <div>{e.text}{hasData && <span className="muted tiny"> {open.has(i) ? '▾' : '▸ details'}</span>}</div>
                {hasData && open.has(i) && <div className="trace-data">{preview(e.data)}</div>}
              </div>
            </div>
          )
        })}
        {shown.length === 0 && <div className="empty">No events yet.</div>}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ Usage

function UsageTab({ deal }: { deal: Deal }) {
  const rows = Object.values(deal.steps).filter((s) => s.kind === 'agent')
  const u = deal.usage
  const maxCost = Math.max(...rows.map((s) => s.usage?.cost_usd ?? 0), 0.000001)
  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="grid g4">
        <Stat label="Input tokens" value={fmtInt(u?.input_tokens)} foot={`${fmtInt(u?.cached_tokens)} cached (${u?.cache_hit_pct ?? 0}%)`} />
        <Stat label="Output tokens" value={fmtInt(u?.output_tokens)} foot={`${fmtInt(u?.reasoning_tokens)} of them reasoning`} />
        <Stat label="Model calls / tool calls" value={`${u?.requests ?? 0} / ${u?.tool_calls ?? 0}`} foot="shared per-run limits apply" />
        <Stat label="Cost of this run" value={fmtUsd(u?.cost_usd)} foot="at the configured gpt-6-luna prices" />
      </div>
      <Section title="By agent">
        <table className="tbl">
          <thead>
            <tr><th>Agent</th><th className="num">Rounds</th><th className="num">Seconds</th><th className="num">Input</th><th className="num">Cached</th><th className="num">Output</th><th className="num">Reasoning</th><th className="num">Calls</th><th className="num">Tools</th><th className="num">Cost</th><th style={{ width: 140 }}></th></tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.key}>
                <td className="strong">{s.label}</td>
                <td className="num">{s.rounds ?? 0}</td>
                <td className="num">{s.seconds ?? '–'}</td>
                <td className="num">{fmtInt(s.usage?.input_tokens)}</td>
                <td className="num">{fmtInt(s.usage?.cached_tokens)}</td>
                <td className="num">{fmtInt(s.usage?.output_tokens)}</td>
                <td className="num">{fmtInt(s.usage?.reasoning_tokens)}</td>
                <td className="num">{s.usage?.requests ?? 0}</td>
                <td className="num">{s.usage?.tool_calls ?? 0}</td>
                <td className="num">{fmtUsd(s.usage?.cost_usd)}</td>
                <td><Bar value={s.usage?.cost_usd ?? 0} max={maxCost} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
    </div>
  )
}

// ------------------------------------------------------------------ Decision

function DecisionBar({ deal, onDone }: { deal: Deal; onDone: (d: Deal) => void }) {
  const [note, setNote] = useState('')
  const [party, setParty] = useState(0)
  const [manual, setManual] = useState('')
  const [quality, setQuality] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const decide = async (action: string) => {
    setBusy(true)
    setErr(null)
    try {
      await api.post(`/api/deals/${deal.id}/decision`, {
        action,
        note,
        manual_hours: manual.trim() ? Number(manual) : null,
        quality: quality ? Number(quality) : null,
      })
      if (action === 'approve') setParty((n) => n + 1)
      onDone(await api.get<Deal>(`/api/deals/${deal.id}`))
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }
  const d = deal.decision
  let body: ReactNode
  if (d) {
    body = (
      <div className="row">
        <StatusPill status={deal.status} />
        <span className="small">by <b>{d.approver}</b> on {fmtDateTime(d.at)}</span>
        {d.note && <span className="small muted">“{d.note}”</span>}
        {d.manual_hours != null && <Pill tone="blue">manual: {d.manual_hours} h vs app: {d.app_minutes} min</Pill>}
        {d.quality != null && <Pill tone="green">draft quality {d.quality}/5</Pill>}
      </div>
    )
  } else {
    body = (
      <div className="col">
        <div className="row" style={{ alignItems: 'stretch' }}>
          <input placeholder={deal.results.quote?.needs_approval ? 'Required: why approve outside policy?' : 'Note (optional)'} value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, minWidth: 240 }} />
          <button className="btn btn-primary" disabled={busy} onClick={() => decide('approve')}>Approve to send</button>
          <button className="btn" disabled={busy} onClick={() => decide('request_changes')}>Request changes</button>
          <button className="btn btn-danger" disabled={busy} onClick={() => decide('reject')}>Reject</button>
        </div>
        <div className="row small muted">
          <span>Optional, for measuring impact:</span>
          <input type="number" min="0" step="0.5" placeholder="Hours this quote takes by hand" value={manual} onChange={(e) => setManual(e.target.value)} style={{ width: 230 }} />
          <select value={quality} onChange={(e) => setQuality(e.target.value)} style={{ width: 210 }}>
            <option value="">Draft quality (1–5)…</option>
            <option value="5">5: send as is</option>
            <option value="4">4: light edits</option>
            <option value="3">3: useful start</option>
            <option value="2">2: major rework</option>
            <option value="1">1: not useful</option>
          </select>
        </div>
        {err && <div className="notice red small">{err}</div>}
      </div>
    )
  }
  return (
    <div className="card card-pad no-print" style={{ borderColor: deal.decision ? undefined : 'var(--accent)', position: 'relative' }}>
      {party > 0 && <Confetti key={party} />}
      <div className="row" style={{ marginBottom: d ? 0 : 10 }}>
        <h3>Your decision</h3>
        <span className="muted small">The agents only draft. A person approves before anything reaches the client.</span>
      </div>
      {body}
    </div>
  )
}
