import { useEffect, useMemo, useState } from 'react'
import { TriangleAlert, ArrowRight, CalendarClock, GraduationCap, Play } from 'lucide-react'
import { ApiError, api } from '../api'
import { Bar, List, Pill, ROLE_LABEL, Section, Stat, StatusPill, fmtDate, fmtDateTime, fmtInt, fmtUsd } from '../lib'
import { Markdown } from '../markdown'
import type { Usage } from '../types'

// ------------------------------------------------------------------ types (Bench Optimizer API)

type Rolloff = {
  emp_id: string
  name: string
  role: string
  title: string
  level: string
  office: string
  skills: string[]
  free_from: string
  weeks_until_free: number
  free_pct: number
  status: 'on_bench_now' | 'rolling_off'
  fully_free: boolean
  leave_weeks: number
  bench_hours: number
  bench_cost_inr: number
  ending_project: { project: string; ends: string } | null
  next_project: { project: string; starts: string; allocation_pct: number } | null
}
type Week = { week: string; bench_fte: number; bench_cost_inr: number; fully_free: number; on_leave: number }
type DealDemand = {
  deal_id: string
  title: string
  client: string
  status: string
  win_probability: number
  start: string | null
  end: string | null
  roles: { role: string; hours: number; fte_needed: number; uncovered: boolean }[]
  stack: string[]
  link: string
}
type Internal = { id: string; name: string; roles: string[]; skills: string[]; capacity_fte: number; min_weeks: number; priority: string; value: string }
type Gap = { skill: string; demand_score: number; deals: string[]; people_with_skill: number; coming_free_with_skill: number; gap: boolean; courses: string[] }
type Forecast = {
  as_of: string
  horizon_weeks: number
  horizon_end: string
  rolloffs: Rolloff[]
  weekly: Week[]
  deals: DealDemand[]
  internal: Internal[]
  gaps: Gap[]
  totals: {
    people_rolling_off: number
    on_bench_now: number
    rolling_off_later: number
    bench_fte_avg_8w: number
    bench_cost_if_nothing_inr: number
    bench_cost_8w_inr: number
  }
}
type MatchRow = {
  emp_id: string
  name: string
  title: string
  role: string
  target_type: 'deal' | 'internal'
  target_id: string
  target_name: string
  link: string | null
  start_date: string
  weeks: number
  allocation_pct: number
  fit: string
  matched_skills: string[]
  confidence: string
  rationale: string
  win_probability: number
  hours_in_horizon: number
  status: string
  issues: string[]
  source?: string
}
type UpskillRow = {
  emp_id: string
  name: string
  title: string
  course_id: string
  course: string
  skill: string
  provider: string
  course_hours: number
  cost_inr: number
  hours_per_week: number
  start_date: string
  end_date: string
  reason: string
  status: string
  issues: string[]
}
type Value = {
  bench_hours_if_nothing: number
  bench_cost_if_nothing_inr: number
  billable_hours_expected: number
  billable_hours_if_all_deals_won: number
  bench_cost_covered_by_billable_inr: number
  internal_hours: number
  internal_investment_inr: number
  training_hours: number
  course_fees_inr: number
  idle_cost_remaining_inr: number
  people_rolling_off: number
  people_matched: number
  people_upskilled: number
  people_without_plan: number
}
type Step = { key: string; label: string; kind: string; status: string; summary?: string; seconds?: number; usage?: Usage }
type BenchRun = {
  id: string
  title: string
  status: string
  created_at: string
  created_by?: string
  input: { horizon_weeks: number; min_free_pct: number }
  steps: Record<string, Step>
  usage?: Usage
  error: string | null
  decision: { action: string; note: string; approver: string; at: string } | null
  results: {
    matches?: MatchRow[]
    rejected_matches?: { emp_id?: string; target_id?: string; issues: string[] }[]
    upskilling?: UpskillRow[]
    rejected_upskilling?: { emp_id?: string; course_id?: string; issues: string[] }[]
    value?: Value
    brief?: { headline: string; summary: string; decisions_needed: string[]; risks: string[] }
  }
}
type RunRow = { id: string; title: string; status: string; created_at: string; created_by?: string; people_matched?: number; covered_inr?: number; cost_usd?: number; decision?: string }

// ------------------------------------------------------------------ helpers

const inr = (n: number | null | undefined) => (n == null ? '–' : `₹${Math.round(n).toLocaleString('en-IN')}`)
const inrShort = (n: number | null | undefined) => {
  if (n == null) return '–'
  if (n >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`
  if (n >= 1e5) return `₹${(n / 1e5).toFixed(1)} L`
  return inr(n)
}
const role = (r: string) => ROLE_LABEL[r] ?? r
const confTone = (c: string) => (c === 'high' ? 'green' : c === 'medium' ? 'blue' : 'amber')
const fitTone = (f: string) => (f === 'strong' ? 'green' : f === 'partial' ? 'blue' : 'amber')

// ------------------------------------------------------------------ page

export default function Bench() {
  const [weeks, setWeeks] = useState(12)
  const [fc, setFc] = useState<Forecast | null>(null)
  const [denied, setDenied] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [runs, setRuns] = useState<RunRow[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [run, setRun] = useState<BenchRun | null>(null)
  const [starting, setStarting] = useState(false)

  useEffect(() => {
    setFc(null)
    api
      .get<Forecast>(`/api/bench/forecast?weeks=${weeks}`)
      .then(setFc)
      .catch((e) => (e instanceof ApiError && e.status === 403 ? setDenied(true) : setErr((e as Error).message)))
  }, [weeks])

  const loadRuns = () =>
    api
      .get<RunRow[]>('/api/bench/runs')
      .then((r) => {
        setRuns(r)
        setRunId((cur) => cur ?? r[0]?.id ?? null)
      })
      .catch(() => setRuns([]))
  useEffect(() => {
    void loadRuns()
  }, [])

  useEffect(() => {
    if (!runId) return
    let stop = false
    let timer: number | undefined
    const load = async () => {
      try {
        const r = await api.get<BenchRun>(`/api/bench/runs/${runId}`)
        if (stop) return
        setRun(r)
        if (r.status === 'running' || r.status === 'queued') timer = window.setTimeout(load, 1500)
        else void loadRuns()
      } catch (e) {
        if (!stop) setErr((e as Error).message)
      }
    }
    void load()
    return () => {
      stop = true
      if (timer) window.clearTimeout(timer)
    }
  }, [runId])

  const start = async () => {
    setStarting(true)
    setErr(null)
    try {
      const r = await api.post<{ id: string }>('/api/bench/runs', { horizon_weeks: weeks, min_free_pct: 50 })
      setRun(null)
      setRunId(r.id)
    } catch (e) {
      setErr((e as Error).message)
    }
    setStarting(false)
  }

  if (denied)
    return (
      <div className="page">
        <div className="notice amber">The Bench Optimizer is for Directors and HR: bench cost is built from salary data.</div>
      </div>
    )

  const running = run?.status === 'running' || run?.status === 'queued'
  const v = run?.results.value
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">People</div>
          <h1>Bench Optimizer</h1>
          <div className="sub">
            Who comes free in the next weeks and what idle time costs. Three agents match people to upcoming deals or internal
            work and plan short courses toward the skills the pipeline needs; code checks every match.
          </div>
        </div>
        <div className="row">
          <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))} style={{ width: 150 }} aria-label="Horizon">
            {[8, 12, 16].map((w) => (
              <option key={w} value={w}>Next {w} weeks</option>
            ))}
          </select>
          <button className="btn btn-primary" onClick={() => void start()} disabled={starting || running}>
            {starting || running ? <span className="spinner" /> : <Play size={15} />} Plan the bench
          </button>
        </div>
      </div>

      {err && <div className="notice red small">{err}</div>}

      <div className="grid g4">
        <Stat
          label="People coming free"
          value={fc ? fc.totals.people_rolling_off : '…'}
          foot={fc ? `${fc.totals.on_bench_now} free now · ${fc.totals.rolling_off_later} later (≥50% free)` : ''}
        />
        <Stat label="Bench, next 8 weeks" value={fc ? `${fc.totals.bench_fte_avg_8w} FTE` : '…'} foot="average unallocated people per week" />
        <Stat
          label="Bench cost if nothing is done"
          value={fc ? inrShort(fc.totals.bench_cost_if_nothing_inr) : '…'}
          foot={fc ? `${fc.horizon_weeks} weeks · loaded internal cost` : ''}
        />
        <Stat
          label="Covered by the plan (billable)"
          value={v ? inrShort(v.bench_cost_covered_by_billable_inr) : '–'}
          foot={v ? `${fmtInt(v.billable_hours_expected)} h expected · ${fmtInt(v.internal_hours)} h internal` : 'run a plan to see'}
        />
      </div>

      {run && <RunPanel run={run} onDecided={(r) => setRun(r)} />}

      {fc && (
        <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.4fr)' }}>
          <Section title="Weekly bench forecast" right={<span className="tiny muted">from {fmtDate(fc.as_of)}</span>}>
            <WeeklyBars weekly={fc.weekly} />
          </Section>
          <Section title={`Coming free (${fc.rolloffs.length})`}>
            <RolloffTable rows={fc.rolloffs} />
          </Section>
        </div>
      )}

      {fc && (
        <div className="grid g2">
          <Section title="Demand: deals in the pipeline">
            {fc.deals.length === 0 ? (
              <div className="muted small">No Deal Desk deals are approved or awaiting a decision.</div>
            ) : (
              <table className="tbl">
                <thead>
                  <tr><th>Deal</th><th>Status</th><th>Starts</th><th>Roles needed (FTE)</th></tr>
                </thead>
                <tbody>
                  {fc.deals.map((d) => (
                    <tr key={d.deal_id}>
                      <td>
                        <a href={d.link} className="strong">{d.title}</a>
                        <div className="tiny muted">{d.stack.slice(0, 4).join(' · ')}</div>
                      </td>
                      <td>
                        <Pill tone={d.status === 'approved' ? 'green' : 'amber'}>{d.status === 'approved' ? 'approved' : `${Math.round(d.win_probability * 100)}% likely`}</Pill>
                      </td>
                      <td className="small nowrap">{fmtDate(d.start)}</td>
                      <td className="small">
                        {d.roles.filter((r) => !['pm', 'lead'].includes(r.role)).slice(0, 5).map((r) => (
                          <span key={r.role} className="chip" style={{ margin: '0 4px 4px 0' }}>
                            {role(r.role)} <b>{r.fte_needed}</b>
                          </span>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
          <Section title="Demand: internal initiatives">
            <table className="tbl">
              <thead>
                <tr><th>Initiative</th><th>Roles</th><th className="num">FTE</th><th>Priority</th></tr>
              </thead>
              <tbody>
                {fc.internal.map((w) => (
                  <tr key={w.id}>
                    <td>
                      <div className="strong small">{w.name}</div>
                      <div className="tiny muted">{w.value}</div>
                    </td>
                    <td className="small">{w.roles.map(role).join(', ')}</td>
                    <td className="num">{w.capacity_fte}</td>
                    <td><Pill tone={w.priority === 'high' ? 'green' : w.priority === 'medium' ? 'blue' : undefined}>{w.priority}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
        </div>
      )}

      {fc && fc.gaps.length > 0 && (
        <Section title="Skills the pipeline asks for">
          <table className="tbl">
            <thead>
              <tr><th>Skill</th><th className="num">Demand</th><th className="num">People with it</th><th className="num">Coming free</th><th>Courses</th></tr>
            </thead>
            <tbody>
              {fc.gaps.slice(0, 12).map((g) => (
                <tr key={g.skill}>
                  <td className="strong">{g.skill} {g.gap && <Pill tone="red">gap</Pill>}</td>
                  <td className="num">{g.demand_score}</td>
                  <td className="num">{g.people_with_skill}</td>
                  <td className="num">{g.coming_free_with_skill}</td>
                  <td className="small mono muted">{g.courses.join(', ') || '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}

      {runs.length > 0 && (
        <Section title="Past plans">
          <table className="tbl">
            <thead>
              <tr><th>Plan</th><th>Status</th><th>By</th><th className="num">People matched</th><th className="num">Covered</th><th className="num">AI cost</th><th>Created</th></tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id} className="click" onClick={() => setRunId(r.id)} style={r.id === runId ? { background: 'var(--accent-dim)' } : undefined}>
                  <td className="strong">{r.title}</td>
                  <td><StatusPill status={r.status} /></td>
                  <td className="small">{r.created_by ?? '–'}</td>
                  <td className="num">{r.people_matched ?? '–'}</td>
                  <td className="num">{inrShort(r.covered_inr)}</td>
                  <td className="num">{fmtUsd(r.cost_usd)}</td>
                  <td className="small muted nowrap">{fmtDateTime(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
      )}
    </div>
  )
}

// ------------------------------------------------------------------ pieces

function WeeklyBars({ weekly }: { weekly: Week[] }) {
  const max = Math.max(...weekly.map((w) => w.bench_fte), 1)
  return (
    <div className="col" style={{ gap: 7 }}>
      {weekly.map((w) => (
        <div className="bar-row" key={w.week} style={{ gridTemplateColumns: '64px 1fr 150px' }} title={`${w.fully_free} fully free · ${w.on_leave} on leave`}>
          <span className="small muted">{fmtDate(w.week).replace(/ \d{4}$/, '')}</span>
          <Bar value={w.bench_fte} max={max} tone={w.bench_fte > max * 0.8 ? 'amber' : undefined} />
          <span className="small mono right">{w.bench_fte} FTE · {inrShort(w.bench_cost_inr)}</span>
        </div>
      ))}
    </div>
  )
}

function RolloffTable({ rows }: { rows: Rolloff[] }) {
  const [all, setAll] = useState(false)
  const shown = all ? rows : rows.slice(0, 12)
  return (
    <div className="col">
      <table className="tbl">
        <thead>
          <tr><th>Person</th><th>Free from</th><th className="num">Free</th><th>Why</th><th className="num">Bench cost</th></tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr key={r.emp_id}>
              <td>
                <div className="strong small">{r.name}</div>
                <div className="tiny muted">{r.title} · {r.office}</div>
              </td>
              <td className="small nowrap">{r.status === 'on_bench_now' ? <Pill tone="amber">now</Pill> : fmtDate(r.free_from)}</td>
              <td className="num">{r.free_pct}%</td>
              <td className="tiny muted">
                {r.ending_project ? `${r.ending_project.project} ends ${fmtDate(r.ending_project.ends)}` : r.fully_free ? 'no project' : 'part-time on a project'}
                {r.leave_weeks > 0 && ` · ${r.leave_weeks} wk leave`}
                {r.next_project && ` · next: ${r.next_project.project} (${fmtDate(r.next_project.starts)})`}
              </td>
              <td className="num">{inrShort(r.bench_cost_inr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > 12 && (
        <button className="btn btn-ghost btn-sm" onClick={() => setAll((a) => !a)}>{all ? 'Show fewer' : `Show all ${rows.length}`}</button>
      )}
    </div>
  )
}

function RunPanel({ run, onDecided }: { run: BenchRun; onDecided: (r: BenchRun) => void }) {
  const r = run.results
  const v = r.value
  const steps = useMemo(() => Object.values(run.steps), [run.steps])
  const running = run.status === 'running' || run.status === 'queued'
  return (
    <div className="card">
      <div className="card-head">
        <div className="row">
          <h3>{run.title}</h3>
          <StatusPill status={run.status} />
          {run.created_by && <span className="tiny muted">by {run.created_by}</span>}
        </div>
        {run.usage && (
          <span className="chip" title={`${run.usage.input_tokens} input (${run.usage.cached_tokens} cached) · ${run.usage.output_tokens} output`}>
            tokens <b>{fmtInt(run.usage.input_tokens + run.usage.output_tokens)}</b> · <b>{fmtUsd(run.usage.cost_usd)}</b>
          </span>
        )}
      </div>
      <div className="card-body col" style={{ gap: 16 }}>
        <div className="row">
          {steps.map((s, i) => (
            <span key={s.key} className="row" style={{ gap: 6 }}>
              <Pill tone={s.status === 'done' ? 'green' : s.status === 'running' ? 'blue' : s.status === 'failed' ? 'red' : undefined} pulse={s.status === 'running' ? true : undefined}>
                {s.label}{s.seconds != null && s.status === 'done' ? ` · ${s.seconds}s` : ''}
              </Pill>
              {i < steps.length - 1 && <ArrowRight size={13} className="muted" />}
            </span>
          ))}
        </div>
        {running && <div className="notice blue small"><span className="spinner" /> The agents are planning; this takes about half a minute.</div>}
        {run.status === 'failed' && <div className="notice red small">Run failed: {run.error}</div>}

        {r.brief && (
          <div className="notice green">
            <CalendarClock size={18} />
            <div className="col" style={{ gap: 8 }}>
              <div className="strong">{r.brief.headline}</div>
              <Markdown text={r.brief.summary} variant="chat" />
              <div className="grid g2">
                <div>
                  <div className="strong small" style={{ marginBottom: 4 }}>Decisions needed</div>
                  <List items={r.brief.decisions_needed} />
                </div>
                <div>
                  <div className="strong small" style={{ marginBottom: 4 }}>Risks</div>
                  <List items={r.brief.risks} />
                </div>
              </div>
            </div>
          </div>
        )}

        {v && (
          <div className="grid g4">
            <Stat small label="Billable hours (expected)" value={`${fmtInt(v.billable_hours_expected)} h`} foot={`${fmtInt(v.billable_hours_if_all_deals_won)} h if every deal is won`} />
            <Stat small label="Internal work + training" value={`${fmtInt(v.internal_hours + v.training_hours)} h`} foot={`course fees ${inr(v.course_fees_inr)}`} />
            <Stat small label="Idle cost remaining" value={inrShort(v.idle_cost_remaining_inr)} foot={`of ${inrShort(v.bench_cost_if_nothing_inr)} without a plan`} />
            <Stat small label="People" value={`${v.people_matched} matched`} foot={`${v.people_upskilled} upskilled · ${v.people_without_plan} without a plan`} />
          </div>
        )}

        {r.matches && r.matches.length > 0 && (
          <div>
            <h3 style={{ marginBottom: 8 }}>Matches ({r.matches.length})</h3>
            <table className="tbl">
              <thead>
                <tr><th>Person</th><th>Matched to</th><th>From</th><th className="num">Alloc.</th><th>Fit</th><th>Confidence</th><th>Why / checks</th></tr>
              </thead>
              <tbody>
                {r.matches.map((m, i) => (
                  <tr key={`${m.emp_id}-${m.target_id}-${i}`}>
                    <td>
                      <div className="strong small">{m.name}</div>
                      <div className="tiny muted">{m.title}</div>
                    </td>
                    <td className="small">
                      {m.target_type === 'deal' && m.link ? <a href={m.link}>{m.target_name}</a> : m.target_name}
                      <div className="tiny muted">
                        {m.target_type === 'deal' ? `deal · ${Math.round(m.win_probability * 100)}% likely` : 'internal initiative'}
                      </div>
                    </td>
                    <td className="small nowrap">{fmtDate(m.start_date)}<div className="tiny muted">{m.weeks} wk · {fmtInt(m.hours_in_horizon)} h</div></td>
                    <td className="num">{m.allocation_pct}%</td>
                    <td><Pill tone={fitTone(m.fit)}>{m.fit}</Pill></td>
                    <td>
                      {m.source === 'calculator' ? <Pill tone="violet">calculator fill</Pill> : <Pill tone={confTone(m.confidence)}>{m.confidence}</Pill>}
                    </td>
                    <td className="tiny">
                      {m.rationale}
                      {m.issues.length > 0 && <div className="amber row" style={{ gap: 4 }}><TriangleAlert size={12} /> {m.issues.join(' ')}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {r.upskilling && r.upskilling.length > 0 && (
          <div>
            <h3 style={{ marginBottom: 8 }} className="row"><GraduationCap size={17} /> Upskilling plan ({r.upskilling.length})</h3>
            <table className="tbl">
              <thead>
                <tr><th>Person</th><th>Course</th><th>When</th><th className="num">h/week</th><th className="num">Fee</th><th>Why</th></tr>
              </thead>
              <tbody>
                {r.upskilling.map((u, i) => (
                  <tr key={`${u.emp_id}-${u.course_id}-${i}`}>
                    <td>
                      <div className="strong small">{u.name}</div>
                      <div className="tiny muted">{u.title}</div>
                    </td>
                    <td className="small">{u.course}<div className="tiny muted">{u.provider} · {u.course_hours} h · {u.skill}</div></td>
                    <td className="small nowrap">{fmtDate(u.start_date)} → {fmtDate(u.end_date)}</td>
                    <td className="num">{u.hours_per_week}</td>
                    <td className="num">{u.cost_inr ? inr(u.cost_inr) : 'free'}</td>
                    <td className="tiny">
                      {u.reason}
                      {u.issues.length > 0 && <div className="amber row" style={{ gap: 4 }}><TriangleAlert size={12} /> {u.issues.join(' ')}</div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {((r.rejected_matches?.length ?? 0) > 0 || (r.rejected_upskilling?.length ?? 0) > 0) && (
          <div className="notice amber small">
            <div>
              <b>Proposals the checks rejected</b>
              {[...(r.rejected_matches ?? []), ...(r.rejected_upskilling ?? [])].map((x, i) => (
                <div key={i} className="tiny">• {x.issues.join(' ')}</div>
              ))}
            </div>
          </div>
        )}

        {['ready', 'approved', 'rejected'].includes(run.status) && <Decision run={run} onDecided={onDecided} />}
      </div>
    </div>
  )
}

function Decision({ run, onDecided }: { run: BenchRun; onDecided: (r: BenchRun) => void }) {
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const d = run.decision
  if (d)
    return (
      <div className="row small">
        <StatusPill status={run.status} />
        <span>by <b>{d.approver}</b> on {fmtDateTime(d.at)}</span>
        {d.note && <span className="muted">“{d.note}”</span>}
      </div>
    )
  const decide = async (action: 'approve' | 'reject') => {
    setBusy(true)
    setErr(null)
    try {
      await api.post(`/api/bench/runs/${run.id}/decision`, { action, note })
      onDecided(await api.get<BenchRun>(`/api/bench/runs/${run.id}`))
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }
  return (
    <div className="col">
      <div className="row" style={{ flexWrap: 'nowrap' }}>
        <input placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn btn-primary" disabled={busy} onClick={() => void decide('approve')}>Approve plan</button>
        <button className="btn" disabled={busy} onClick={() => void decide('reject')}>Reject</button>
      </div>
      <div className="tiny muted">Approving records the decision; nothing changes in staffing until project managers confirm each move.</div>
      {err && <div className="notice red small">{err}</div>}
    </div>
  )
}
