import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Bar, List, Pill, Section, Stat, StatusPill, fmtDateTime, fmtUsd, go, sevTone, useRoute } from '../lib'
import { Markdown } from '../markdown'

// ------------------------------------------------------------------ types (module-local)

type Usage = { input_tokens: number; cached_tokens: number; output_tokens: number; requests: number; tool_calls: number; cost_usd: number; cache_hit_pct?: number }
type Step = { key: string; label: string; kind: 'agent' | 'code'; job?: string; status: string; seconds?: number; summary?: string; usage?: Usage; rounds?: number }
type Overview = {
  cycle: string
  effective_date: string
  headcount: number
  payroll: number
  default_pool_pct: number
  ratings: Record<string, number>
  promotions_recommended: number
  retention_risk: Record<string, number>
  offices: { office: string; people: number; avg_compa_ratio: number }[]
  managers: { emp_id: string; name: string; team_size: number }[]
}
type RunRow = { id: string; title: string; status: string; created_at: string; created_by?: string; pool_pct: number; avg_hike_pct?: number; verdict?: string; adjustments: number; cost_usd?: number; decision?: string }
type Row = {
  emp_id: string; name: string; title: string; role: string; office: string; manager_emp_id: string; rating: number; evidence_score: number
  promotion_recommended: boolean; retention_risk: string; ctc: number; hike_pct: number; increase: number; new_ctc: number
  promotion_addon_pct: number; compa_before: number; compa_after: number | null; adjusted: boolean
}
type Flag = { emp_id: string; issue: string; current_rating: number; suggested_rating?: number | null; evidence: string; confidence: string }
type Review = { verdict: string; issues: { kind: string; group: string; finding: string; severity: string }[]; adjustments: { emp_id: string; add_pp: number; reason: string }[]; summary: string }
type Metrics = {
  gender_gap_within_rating: { rating: number; women: number; men: number; avg_hike_women: number; avg_hike_men: number; gap_pp_men_minus_women: number }[]
  managers: { manager_emp_id: string; manager: string; team_size: number; avg_rating_minus_evidence: number; women?: number; men?: number; women_rating_minus_evidence?: number; men_rating_minus_evidence?: number; gap?: number }[]
  offices: { office: string; people: number; avg_compa_before: number; avg_compa_after: number; avg_hike_pct: number }[]
  compa_outliers: { emp_id: string; name: string; office: string; rating: number; compa_after: number }[]
  flags: { kind: string; group: string; value: number }[]
}
type RunState = {
  id: string
  title: string
  status: string
  created_at: string
  created_by?: string
  input: { pool_pct: number; note: string }
  steps: Record<string, Step>
  usage?: Usage
  error?: string | null
  decision?: { action: string; note: string; approver: string; at: string } | null
  results: {
    evidence?: { headcount: number; payroll: number; pool_amount: number; managers: Record<string, string> }
    calibration?: { flags: Flag[]; manager_patterns: { manager_emp_id: string; pattern: string }[]; summary: string }
    strategy?: { chosen: Record<string, number>; rationale: string[] }
    summary?: { pool_amount: number; used_amount: number; feasible: boolean; note: string; avg_hike_pct: number; promotions: number; adjusted: number; by_rating: { rating: number; people: number; avg_hike_pct: number; min_hike_pct: number; max_hike_pct: number }[] }
    proposal?: Row[]
    fairness_before?: Metrics
    fairness_after?: Metrics
    reviews?: Review[]
    adjustments_applied?: { emp_id: string; name: string; requested_pp: number; hike_before: number; hike_after: number; reason: string }[]
    briefs?: Record<string, string>
    privacy_findings?: { manager: string; reason: string; text: string }[]
    memo_markdown?: string
  }
}

// ------------------------------------------------------------------ formatting

function inr(n: number | null | undefined): string {
  if (n == null) return '–'
  return '₹' + Math.round(n).toLocaleString('en-IN')
}
function inrShort(n: number | null | undefined): string {
  if (n == null) return '–'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`
  return inr(n)
}
const pct = (n: number | null | undefined, d = 1) => (n == null ? '–' : `${n.toFixed(d)}%`)
const verdictTone = (v?: string) => (v === 'fair' ? 'green' : v === 'adjust' ? 'violet' : v ? 'amber' : '')

const TABS = ['Proposal', 'Fairness', 'Calibration', 'Strategy', 'Manager briefs', 'HR memo', 'Tokens & cost'] as const
type Tab = (typeof TABS)[number]

// ------------------------------------------------------------------ page

export default function Appraisals() {
  const route = useRoute()
  const runId = route[0] === 'appraisals' && route[1] ? route[1] : null
  const [overview, setOverview] = useState<Overview | null>(null)
  const [runs, setRuns] = useState<RunRow[]>([])
  const [pool, setPool] = useState('9')
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.get<Overview>('/api/appraisals/overview').then((o) => { setOverview(o); setPool(String(o.default_pool_pct)) }).catch((e) => setErr((e as Error).message))
  }, [])
  useEffect(() => {
    api.get<RunRow[]>('/api/appraisals/runs').then(setRuns).catch(() => setRuns([]))
  }, [runId])

  const start = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.post<{ id: string }>('/api/appraisals/runs', { pool_pct: Number(pool), note })
      go(`/appraisals/${r.id}`)
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }

  const poolAmount = overview ? (overview.payroll * Number(pool || 0)) / 100 : 0
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">People</div>
          <h1>Appraisal &amp; Hike Planner</h1>
          <div className="sub">
            Split a fixed hike budget fairly. Agents check ratings against evidence, choose how to weigh performance, market and
            retention, and audit the result for unfair gaps; code computes every hike so the pool adds up to the rupee. HR approves.
          </div>
        </div>
        {runId && <button className="btn btn-sm" onClick={() => go('/appraisals')}>← All cycles</button>}
      </div>

      {err && <div className="notice red small">{err}</div>}

      {!runId && (
        <>
          {overview && (
            <div className="grid g4">
              <Stat label="People in this cycle" value={overview.headcount} foot={`${overview.managers.length} managers · ${overview.cycle}`} />
              <Stat label="Annual payroll" value={inrShort(overview.payroll)} foot="current CTC, all staff" />
              <Stat label="Recommended for promotion" value={overview.promotions_recommended} foot="by managers" />
              <Stat label="High retention risk" value={overview.retention_risk.high ?? 0} foot="strong performers below market" />
            </div>
          )}
          <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1.2fr) minmax(0, 1fr)' }}>
            <Section title="Start a hike cycle">
              <div className="col" style={{ gap: 14 }}>
                <div className="row" style={{ alignItems: 'flex-end', flexWrap: 'nowrap' }}>
                  <label className="field" style={{ width: 200 }}>
                    Budget pool (% of payroll)
                    <input type="number" min={2} max={20} step={0.5} value={pool} onChange={(e) => setPool(e.target.value)} />
                  </label>
                  <div className="col" style={{ gap: 2 }}>
                    <span className="tiny muted">Pool to distribute</span>
                    <span className="strong" style={{ fontSize: 20 }}>{inrShort(poolAmount)}</span>
                  </div>
                </div>
                <label className="field">
                  Note for the agents <span className="hint">(optional, e.g. "retention in Bhopal is a concern")</span>
                  <textarea value={note} onChange={(e) => setNote(e.target.value)} style={{ minHeight: 80 }} maxLength={1500} />
                </label>
                <div className="row">
                  <button className="btn btn-primary" disabled={busy || !overview} onClick={() => void start()}>
                    {busy ? 'Starting…' : 'Run the cycle'}
                  </button>
                  <span className="small muted">About 1–2 minutes. Nothing is shared with managers until HR approves.</span>
                </div>
              </div>
            </Section>
            <Section title="Ratings and market position">
              {overview ? (
                <div className="col" style={{ gap: 12 }}>
                  <div className="col" style={{ gap: 6 }}>
                    {[5, 4, 3, 2, 1].map((r) => (
                      <div className="bar-row" key={r}>
                        <span>Rating {r}</span>
                        <Bar value={overview.ratings[String(r)] ?? 0} max={overview.headcount} />
                        <span className="mono right">{overview.ratings[String(r)] ?? 0}</span>
                      </div>
                    ))}
                  </div>
                  <table className="tbl">
                    <thead><tr><th>Office</th><th className="num">People</th><th className="num">Avg compa-ratio</th></tr></thead>
                    <tbody>
                      {overview.offices.map((o) => (
                        <tr key={o.office}>
                          <td>{o.office}</td><td className="num">{o.people}</td>
                          <td className="num">{o.avg_compa_ratio.toFixed(2)} {o.avg_compa_ratio < 0.9 && <Pill tone="amber">below market</Pill>}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="muted small">Loading…</div>
              )}
            </Section>
          </div>
          <Section title="Hike cycles">
            {runs.length === 0 ? (
              <div className="muted small">No cycles yet. Start one above.</div>
            ) : (
              <table className="tbl">
                <thead><tr><th>Cycle</th><th>Status</th><th className="num">Avg hike</th><th>Fairness</th><th className="num">Adjusted</th><th className="num">AI cost</th><th>Started</th></tr></thead>
                <tbody>
                  {runs.map((r) => (
                    <tr key={r.id} className="click" onClick={() => go(`/appraisals/${r.id}`)}>
                      <td><div className="strong">{r.title}</div><div className="tiny muted">{r.created_by ?? ''}</div></td>
                      <td><StatusPill status={r.status} /></td>
                      <td className="num">{pct(r.avg_hike_pct)}</td>
                      <td>{r.verdict ? <Pill tone={verdictTone(r.verdict)}>{r.verdict}</Pill> : '–'}</td>
                      <td className="num">{r.adjustments}</td>
                      <td className="num">{fmtUsd(r.cost_usd)}</td>
                      <td className="small muted">{fmtDateTime(r.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
        </>
      )}

      {runId && <RunView id={runId} />}
    </div>
  )
}

// ------------------------------------------------------------------ one run

function RunView({ id }: { id: string }) {
  const [run, setRun] = useState<RunState | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('Proposal')

  useEffect(() => {
    let stop = false
    let timer: number | undefined
    const load = async () => {
      try {
        const r = await api.get<RunState>(`/api/appraisals/runs/${id}`)
        if (stop) return
        setRun(r)
        if (r.status === 'running' || r.status === 'queued') timer = window.setTimeout(load, 1500)
      } catch (e) {
        if (!stop) setErr((e as Error).message)
      }
    }
    void load()
    return () => {
      stop = true
      if (timer) window.clearTimeout(timer)
    }
  }, [id])

  if (err) return <div className="notice red small">{err}</div>
  if (!run) return <div className="muted small">Loading…</div>
  const r = run.results
  const sm = r.summary
  const finalReview = r.reviews?.[r.reviews.length - 1]
  const running = run.status === 'running' || run.status === 'queued'

  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="row">
        <h2 style={{ margin: 0 }}>{run.title}</h2>
        <StatusPill status={run.status} />
        {run.created_by && <span className="chip">by <b>{run.created_by}</b></span>}
        {run.usage && <span className="chip">AI cost <b>{fmtUsd(run.usage.cost_usd)}</b></span>}
      </div>
      {run.error && <div className="notice red small">Run failed: {run.error}</div>}

      <Section title="Agents and checks" right={running ? <span className="small muted">working… this page updates live</span> : null}>
        <table className="tbl">
          <tbody>
            {Object.values(run.steps).map((s) => (
              <tr key={s.key}>
                <td style={{ width: 210 }}>
                  <div className="strong">{s.label}</div>
                  <div className="tiny muted">{s.kind === 'code' ? 'code' : 'agent'}{(s.rounds ?? 0) > 1 ? ` · ${s.rounds} rounds` : ''}</div>
                </td>
                <td style={{ width: 120 }}><Pill tone={s.status === 'done' ? 'green' : s.status === 'running' ? 'blue' : s.status === 'failed' ? 'red' : ''}>{s.status}</Pill></td>
                <td className="small">{s.summary ?? <span className="muted">{s.job}</span>}</td>
                <td className="num small muted" style={{ width: 70 }}>{s.seconds != null ? `${s.seconds}s` : ''}</td>
                <td className="num small muted" style={{ width: 80 }}>{s.usage ? fmtUsd(s.usage.cost_usd) : ''}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      {sm && (
        <div className="grid g4">
          <Stat label="Pool allocated" value={inrShort(sm.used_amount)} foot={sm.used_amount === sm.pool_amount ? `exactly the pool (${inr(sm.pool_amount)})` : sm.note} />
          <Stat label="Average hike" value={pct(sm.avg_hike_pct)} foot={`${sm.promotions} promotions included`} />
          <Stat label="Adjusted by the Fairness Auditor" value={r.adjustments_applied?.length ?? 0} foot="pool rebalanced around them" />
          <Stat label="Fairness verdict" value={finalReview ? finalReview.verdict : '…'} foot={finalReview ? `${finalReview.issues.length} issues in the final review` : ''} small />
        </div>
      )}

      {sm && (
        <div className="row">
          {TABS.map((t) => (
            <button key={t} className={`btn btn-sm ${tab === t ? 'btn-primary' : ''}`} onClick={() => setTab(t)}>{t}</button>
          ))}
        </div>
      )}

      {sm && tab === 'Proposal' && <ProposalTab run={run} />}
      {sm && tab === 'Fairness' && <FairnessTab run={run} />}
      {sm && tab === 'Calibration' && <CalibrationTab run={run} />}
      {sm && tab === 'Strategy' && r.strategy && (
        <Section title="Hike Strategist's weighting">
          <div className="col" style={{ gap: 6, marginBottom: 12 }}>
            {Object.entries(r.strategy.chosen).map(([k, v]) => (
              <div className="bar-row" key={k}>
                <span>{k.replace(/_/g, ' ')}</span>
                <Bar value={k === 'promotion_share_pct' ? v : v * 100} max={k === 'promotion_share_pct' ? 25 : 100} />
                <span className="mono right">{k === 'promotion_share_pct' ? `${v}%` : v}</span>
              </div>
            ))}
          </div>
          <List items={r.strategy.rationale} />
        </Section>
      )}
      {sm && tab === 'Manager briefs' && <BriefsTab run={run} />}
      {sm && tab === 'HR memo' && (r.memo_markdown ? <Markdown text={r.memo_markdown} /> : <div className="muted small">Not ready yet.</div>)}
      {sm && tab === 'Tokens & cost' && (
        <Section title="Measured tokens and cost">
          <table className="tbl">
            <thead><tr><th>Step</th><th className="num">Input</th><th className="num">Cached</th><th className="num">Output</th><th className="num">Calls</th><th className="num">Tools</th><th className="num">Cost</th></tr></thead>
            <tbody>
              {Object.values(run.steps).filter((s) => s.kind === 'agent').map((s) => (
                <tr key={s.key}>
                  <td>{s.label}</td>
                  <td className="num">{s.usage?.input_tokens ?? 0}</td><td className="num">{s.usage?.cached_tokens ?? 0}</td>
                  <td className="num">{s.usage?.output_tokens ?? 0}</td><td className="num">{s.usage?.requests ?? 0}</td>
                  <td className="num">{s.usage?.tool_calls ?? 0}</td><td className="num">{fmtUsd(s.usage?.cost_usd)}</td>
                </tr>
              ))}
              {run.usage && (
                <tr>
                  <td className="strong">Total</td>
                  <td className="num strong">{run.usage.input_tokens}</td><td className="num strong">{run.usage.cached_tokens}</td>
                  <td className="num strong">{run.usage.output_tokens}</td><td className="num strong">{run.usage.requests}</td>
                  <td className="num strong">{run.usage.tool_calls}</td><td className="num strong">{fmtUsd(run.usage.cost_usd)}</td>
                </tr>
              )}
            </tbody>
          </table>
        </Section>
      )}

      {['ready', 'approved', 'rejected', 'changes_requested'].includes(run.status) && <DecisionBar run={run} onDone={setRun} />}
    </div>
  )
}

function ProposalTab({ run }: { run: RunState }) {
  const r = run.results
  const managers = r.evidence?.managers ?? {}
  const [mgr, setMgr] = useState('all')
  const [office, setOffice] = useState('all')
  const flagged = useMemo(() => new Set((r.calibration?.flags ?? []).map((f) => f.emp_id)), [r.calibration])
  const rows = (r.proposal ?? [])
    .filter((x) => (mgr === 'all' || x.manager_emp_id === mgr) && (office === 'all' || x.office === office))
    .sort((a, b) => b.hike_pct - a.hike_pct)
  const offices = Array.from(new Set((r.proposal ?? []).map((x) => x.office))).sort()
  const maxAvg = Math.max(...(r.summary?.by_rating.map((b) => b.avg_hike_pct) ?? [1]), 1)
  return (
    <div className="col" style={{ gap: 16 }}>
      <Section title="Average hike by rating">
        <div className="col" style={{ gap: 6 }}>
          {r.summary?.by_rating.map((b) => (
            <div className="bar-row" key={b.rating}>
              <span>Rating {b.rating} <span className="muted tiny">({b.people})</span></span>
              <Bar value={b.avg_hike_pct} max={maxAvg} />
              <span className="mono right">{pct(b.avg_hike_pct)}</span>
            </div>
          ))}
        </div>
      </Section>
      <Section
        title={`Proposed hikes (${rows.length})`}
        right={
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <select value={mgr} onChange={(e) => setMgr(e.target.value)} style={{ width: 210 }}>
              <option value="all">All managers</option>
              {Object.entries(managers).map(([k, v]) => <option key={k} value={k}>{v} ({k})</option>)}
            </select>
            <select value={office} onChange={(e) => setOffice(e.target.value)} style={{ width: 140 }}>
              <option value="all">All offices</option>
              {offices.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          </div>
        }
      >
        <div style={{ overflowX: 'auto' }}>
          <table className="tbl">
            <thead>
              <tr>
                <th>Person</th><th>Office</th><th>Manager</th><th className="num">Rating</th><th className="num">Evidence</th>
                <th className="num">Compa</th><th className="num">Hike</th><th className="num">Increase</th><th className="num">New CTC</th><th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((x) => (
                <tr key={x.emp_id}>
                  <td><div className="strong">{x.name}</div><div className="tiny muted">{x.title} · {x.emp_id}</div></td>
                  <td>{x.office}</td>
                  <td className="small">{managers[x.manager_emp_id] ?? (x.manager_emp_id || 'Director')}</td>
                  <td className="num">{x.rating}</td>
                  <td className="num">{x.evidence_score.toFixed(1)}</td>
                  <td className="num">{x.compa_before.toFixed(2)} → {x.compa_after != null ? x.compa_after.toFixed(2) : '–'}</td>
                  <td className="num strong">{pct(x.hike_pct)}</td>
                  <td className="num">{inr(x.increase)}</td>
                  <td className="num">{inr(x.new_ctc)}</td>
                  <td>
                    <div className="row" style={{ gap: 4 }}>
                      {x.promotion_addon_pct > 0 && <Pill tone="green">promotion</Pill>}
                      {x.adjusted && <Pill tone="violet">fairness adj.</Pill>}
                      {flagged.has(x.emp_id) && <Pill tone="amber">calibration</Pill>}
                      {x.retention_risk === 'high' && <Pill tone="red">retention risk</Pill>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>
    </div>
  )
}

function FairnessTab({ run }: { run: RunState }) {
  const r = run.results
  const m = r.fairness_after ?? r.fairness_before
  return (
    <div className="col" style={{ gap: 16 }}>
      {(r.reviews ?? []).map((rv, i) => (
        <Section key={i} title={`Fairness review, round ${i + 1}${i === (r.reviews?.length ?? 0) - 1 ? ' (final)' : ''}`} right={<Pill tone={verdictTone(rv.verdict)}>{rv.verdict}</Pill>}>
          <p className="small" style={{ marginBottom: 10 }}>{rv.summary}</p>
          <table className="tbl">
            <thead><tr><th>Severity</th><th>Kind</th><th>Group</th><th>Finding</th></tr></thead>
            <tbody>
              {rv.issues.map((x, k) => (
                <tr key={k}><td><Pill tone={sevTone(x.severity)}>{x.severity}</Pill></td><td className="small">{x.kind.replace(/_/g, ' ')}</td><td className="small">{x.group}</td><td className="small">{x.finding}</td></tr>
              ))}
            </tbody>
          </table>
          {i > 0 && rv.adjustments.length > 0 && <div className="tiny muted" style={{ marginTop: 8 }}>Round-2 adjustments are recommendations for HR, not applied.</div>}
        </Section>
      ))}
      {(r.adjustments_applied?.length ?? 0) > 0 && (
        <Section title="Adjustments applied (pool rebalanced in code)">
          <table className="tbl">
            <thead><tr><th>Person</th><th className="num">Before</th><th className="num">After</th><th>Reason</th></tr></thead>
            <tbody>
              {r.adjustments_applied!.map((a) => (
                <tr key={a.emp_id}><td><div className="strong">{a.name}</div><div className="tiny muted">{a.emp_id}</div></td><td className="num">{pct(a.hike_before)}</td><td className="num strong">{pct(a.hike_after)}</td><td className="small">{a.reason}</td></tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
      {m && (
        <div className="grid g2">
          <Section title="Ratings vs evidence by manager">
            <table className="tbl">
              <thead><tr><th>Manager</th><th className="num">Team</th><th className="num">All</th><th className="num">Women</th><th className="num">Men</th></tr></thead>
              <tbody>
                {m.managers.map((x) => (
                  <tr key={x.manager_emp_id}>
                    <td className="small">{x.manager} <span className="muted">({x.manager_emp_id})</span></td>
                    <td className="num">{x.team_size}</td>
                    <td className="num">{x.avg_rating_minus_evidence.toFixed(2)}</td>
                    <td className="num">{x.women_rating_minus_evidence != null ? x.women_rating_minus_evidence.toFixed(2) : '–'}</td>
                    <td className="num">{x.men_rating_minus_evidence != null ? x.men_rating_minus_evidence.toFixed(2) : '–'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="tiny muted" style={{ marginTop: 6 }}>Average (rating − evidence score). Negative = rated below the evidence. Gender is used only in these aggregates.</div>
          </Section>
          <Section title="Market position by office (compa-ratio)">
            <table className="tbl">
              <thead><tr><th>Office</th><th className="num">People</th><th className="num">Before</th><th className="num">After</th><th className="num">Avg hike</th></tr></thead>
              <tbody>
                {m.offices.map((o) => (
                  <tr key={o.office}><td>{o.office}</td><td className="num">{o.people}</td><td className="num">{o.avg_compa_before.toFixed(3)}</td><td className="num">{o.avg_compa_after.toFixed(3)}</td><td className="num">{pct(o.avg_hike_pct)}</td></tr>
                ))}
              </tbody>
            </table>
          </Section>
          <Section title="Average hike by gender within each rating">
            <table className="tbl">
              <thead><tr><th className="num">Rating</th><th className="num">Women</th><th className="num">Men</th><th className="num">Gap (pp)</th></tr></thead>
              <tbody>
                {m.gender_gap_within_rating.map((g) => (
                  <tr key={g.rating}><td className="num">{g.rating}</td><td className="num">{pct(g.avg_hike_women, 2)} <span className="muted tiny">({g.women})</span></td><td className="num">{pct(g.avg_hike_men, 2)} <span className="muted tiny">({g.men})</span></td><td className="num">{g.gap_pp_men_minus_women.toFixed(2)}</td></tr>
                ))}
              </tbody>
            </table>
          </Section>
          <Section title="Pay outliers after the cycle">
            {m.compa_outliers.length === 0 ? <div className="muted small">None.</div> : (
              <table className="tbl">
                <thead><tr><th>Person</th><th>Office</th><th className="num">Rating</th><th className="num">Compa after</th></tr></thead>
                <tbody>{m.compa_outliers.map((o) => <tr key={o.emp_id}><td>{o.name}</td><td>{o.office}</td><td className="num">{o.rating}</td><td className="num">{o.compa_after.toFixed(2)}</td></tr>)}</tbody>
              </table>
            )}
          </Section>
        </div>
      )}
    </div>
  )
}

function CalibrationTab({ run }: { run: RunState }) {
  const c = run.results.calibration
  const names = new Map((run.results.proposal ?? []).map((x) => [x.emp_id, x.name]))
  if (!c) return <div className="muted small">Not ready yet.</div>
  return (
    <div className="col" style={{ gap: 16 }}>
      <Section title="Calibration Analyst's summary"><p className="small">{c.summary}</p></Section>
      <Section title={`Ratings vs evidence (${c.flags.length} flags)`}>
        <table className="tbl">
          <thead><tr><th>Person</th><th>Issue</th><th className="num">Rating</th><th className="num">Suggested</th><th>Evidence</th><th>Confidence</th></tr></thead>
          <tbody>
            {c.flags.map((f, i) => (
              <tr key={i}>
                <td><div className="strong">{names.get(f.emp_id) ?? f.emp_id}</div><div className="tiny muted">{f.emp_id}</div></td>
                <td className="small">{f.issue.replace(/_/g, ' ')}</td>
                <td className="num">{f.current_rating}</td>
                <td className="num">{f.suggested_rating ?? '–'}</td>
                <td className="small">{f.evidence}</td>
                <td><Pill tone={f.confidence === 'high' ? 'red' : f.confidence === 'medium' ? 'amber' : 'blue'}>{f.confidence}</Pill></td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="tiny muted" style={{ marginTop: 6 }}>Ratings stay the managers' call; HR decides whether to re-review. The analyst never sees gender or pay.</div>
      </Section>
      {c.manager_patterns.length > 0 && (
        <Section title="Manager patterns">
          <List items={c.manager_patterns.map((p) => `${p.manager_emp_id}: ${p.pattern}`)} />
        </Section>
      )}
    </div>
  )
}

function BriefsTab({ run }: { run: RunState }) {
  const briefs = run.results.briefs ?? {}
  const managers = run.results.evidence?.managers ?? {}
  const keys = Object.keys(briefs)
  const [sel, setSel] = useState(keys[0] ?? '')
  const findings = run.results.privacy_findings ?? []
  return (
    <div className="col" style={{ gap: 12 }}>
      <div className="row">
        {keys.map((k) => (
          <button key={k} className={`btn btn-sm ${k === sel ? 'btn-primary' : ''}`} onClick={() => setSel(k)}>{managers[k] ?? k}</button>
        ))}
      </div>
      {findings.length > 0 ? (
        <div className="notice amber small">The privacy check removed {findings.length} line(s) that mentioned another team, gender or internal text.</div>
      ) : (
        <div className="notice green small">Privacy check: each brief mentions only that manager's own team.</div>
      )}
      {sel && briefs[sel] ? <Markdown text={briefs[sel]} /> : <div className="muted small">No briefs yet.</div>}
    </div>
  )
}

function DecisionBar({ run, onDone }: { run: RunState; onDone: (r: RunState) => void }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const decide = async (action: string) => {
    setBusy(true)
    setErr(null)
    try {
      await api.post(`/api/appraisals/runs/${run.id}/decision`, { action, note })
      onDone(await api.get<RunState>(`/api/appraisals/runs/${run.id}`))
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }
  const d = run.decision
  return (
    <div className="card card-pad">
      <div className="row" style={{ marginBottom: d ? 0 : 10 }}>
        <h3>HR decision</h3>
        <span className="muted small">Agents only draft. Hikes and manager briefs are released after approval.</span>
      </div>
      {d ? (
        <div className="row">
          <StatusPill status={run.status} />
          <span className="small">by <b>{d.approver}</b> on {fmtDateTime(d.at)}</span>
          {d.note && <span className="small muted">“{d.note}”</span>}
        </div>
      ) : (
        <div className="col">
          <div className="row" style={{ alignItems: 'stretch' }}>
            <input placeholder="Note (required if the privacy check removed anything)" value={note} onChange={(e) => setNote(e.target.value)} style={{ flex: 1, minWidth: 260 }} />
            <button className="btn btn-primary" disabled={busy} onClick={() => void decide('approve')}>Approve</button>
            <button className="btn" disabled={busy} onClick={() => void decide('request_changes')}>Request changes</button>
            <button className="btn" disabled={busy} onClick={() => void decide('reject')}>Reject</button>
          </div>
          {err && <div className="notice red small">{err}</div>}
        </div>
      )}
    </div>
  )
}
