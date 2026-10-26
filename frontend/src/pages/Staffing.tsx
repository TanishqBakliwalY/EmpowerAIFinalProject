import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Pill, ROLE_LABEL, Stat, fmtDate, fmtInt, fmtUsd } from '../lib'
import type { Board, StaffingRun } from '../types'

const cellClass = (a: number, leave: boolean) => {
  if (leave) return 'cleave'
  if (a > 100) return 'cover'
  if (a >= 100) return 'c100'
  if (a >= 75) return 'c75'
  if (a >= 50) return 'c50'
  if (a > 0) return 'c25'
  return 'c0'
}

const EXAMPLES = [
  'Who can start a React Native project on 1 Dec at 100% for 3 months?',
  'Which backend developers with .NET Core are free before Christmas?',
  'Do we have anyone for an LLM / RAG chatbot in January?',
  'Who rolls off a project in the next 4 weeks?',
]

export default function Staffing() {
  const [board, setBoard] = useState<Board | null>(null)
  const [role, setRole] = useState('all')
  const [q, setQ] = useState('')
  const [question, setQuestion] = useState('')
  const [asking, setAsking] = useState(false)
  const [answer, setAnswer] = useState<StaffingRun | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    api.get<Board>('/api/staffing/board?weeks=12').then(setBoard).catch((e) => setErr(e.message))
  }, [])

  const people = useMemo(() => {
    if (!board) return []
    const needle = q.trim().toLowerCase()
    return board.people.filter(
      (p) =>
        (role === 'all' || p.role === role) &&
        (!needle || p.name.toLowerCase().includes(needle) || p.skills.some((s) => s.toLowerCase().includes(needle)) || p.title.toLowerCase().includes(needle)),
    )
  }, [board, role, q])

  const ask = async (text?: string) => {
    const qq = (text ?? question).trim()
    if (qq.length < 3) return
    setQuestion(qq)
    setAsking(true)
    setErr(null)
    try {
      setAnswer(await api.post<StaffingRun>('/api/staffing/ask', { question: qq }))
    } catch (e) {
      setErr((e as Error).message)
    }
    setAsking(false)
  }

  const isLeaveWeek = (p: Board['people'][number], i: number) => {
    if (!board) return false
    const ws = board.weeks[i]
    const we = board.week_ends[i]
    return p.assignments.some((a) => a.kind === 'leave' && a.from <= we && a.to >= ws)
  }

  const ans = answer?.results.answer
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Staffing board</h1>
          <div className="sub">
            Who is on what, who is free, and when, for the next 12 weeks. The Deal Desk's Staffing Planner uses exactly this data, and
            the assistant below answers questions about it.
          </div>
        </div>
      </div>

      {board && (
        <div className="grid g4">
          <Stat label="People" value={board.summary.headcount} foot={`as of ${fmtDate(board.as_of)}`} />
          <Stat label="On the bench now" value={board.summary.on_bench_now} foot="100% free this week" />
          <Stat label="Utilisation this week" value={`${board.summary.avg_utilisation_now_pct}%`} foot="average allocation" />
          <Stat
            label="Free capacity, next 4 weeks"
            value={`${board.roles.reduce((s, r) => s + r.free_fte_by_week.slice(0, 4).reduce((a, b) => a + b, 0) / 4, 0).toFixed(1)} FTE`}
            foot="all roles combined"
          />
        </div>
      )}

      <div className="card">
        <div className="card-head">
          <h3>Ask the Staffing Assistant</h3>
          {answer?.usage && <span className="chip">tokens <b>{fmtInt(answer.usage.input_tokens)}</b> in · <b>{fmtInt(answer.usage.output_tokens)}</b> out · <b>{fmtUsd(answer.usage.cost_usd)}</b></span>}
        </div>
        <div className="card-body col">
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && ask()} placeholder="e.g. Who can start a Flutter app on 1 Dec at full time?" />
            <button className="btn btn-primary" disabled={asking || question.trim().length < 3} onClick={() => ask()}>
              {asking ? <span className="spinner" /> : 'Ask'}
            </button>
          </div>
          <div className="row">
            {EXAMPLES.map((x) => (
              <button key={x} className="btn btn-ghost btn-sm" onClick={() => ask(x)} disabled={asking}>{x}</button>
            ))}
          </div>
          {err && <div className="notice red small">{err}</div>}
          {answer?.status === 'failed' && <div className="notice red small">{answer.error}</div>}
          {ans && (
            <div className="col" style={{ gap: 10 }}>
              <div className="notice green"><span>◆</span><div>{ans.answer}</div></div>
              {ans.people.length > 0 && (
                <table className="tbl">
                  <thead><tr><th>Person</th><th className="num">Free</th><th>From</th><th>Why</th></tr></thead>
                  <tbody>
                    {ans.people.map((p) => (
                      <tr key={p.emp_id}>
                        <td><div className="strong">{p.name}</div><div className="tiny muted">{p.title} · <span className="mono">{p.emp_id}</span></div></td>
                        <td className="num">{p.free_pct}%</td>
                        <td className="small">{p.available_from ? fmtDate(p.available_from) : '–'}</td>
                        <td className="small muted">{p.why}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {ans.caveats.length > 0 && <div className="small muted">Caveats: {ans.caveats.join(' · ')}</div>}
            </div>
          )}
        </div>
      </div>

      {board && (
        <div className="card">
          <div className="card-head">
            <h3>Free capacity by role (FTE per week)</h3>
          </div>
          <div className="card-body" style={{ overflowX: 'auto' }}>
            <table className="heat">
              <thead>
                <tr>
                  <th className="left">Role</th>
                  {board.weeks.map((w) => <th key={w}>{new Date(w + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</th>)}
                </tr>
              </thead>
              <tbody>
                {board.roles.map((r) => (
                  <tr key={r.role}>
                    <td className="left small">{r.label} <span className="muted">({r.headcount})</span></td>
                    {r.free_fte_by_week.map((f, i) => (
                      <td key={i} className={`cell ${f >= 2 ? 'c0' : f >= 1 ? 'c25' : f > 0 ? 'c75' : 'c100'}`}>{f.toFixed(1)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {board && (
        <div className="card">
          <div className="card-head">
            <h3>People ({people.length})</h3>
            <div className="row" style={{ flexWrap: 'nowrap' }}>
              <select value={role} onChange={(e) => setRole(e.target.value)} style={{ width: 180 }}>
                <option value="all">All roles</option>
                {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
              <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name or skill…" style={{ width: 220 }} />
            </div>
          </div>
          <div className="card-body" style={{ overflowX: 'auto' }}>
            <div className="legend" style={{ marginBottom: 10 }}>
              <span><i className="c0" /> free</span><span><i className="c25" /> &lt;50% booked</span><span><i className="c50" /> 50–74%</span>
              <span><i className="c75" /> 75–99%</span><span><i className="c100" /> fully booked</span><span><i className="cover" /> over-booked</span><span><i className="cleave" /> leave</span>
            </div>
            <table className="heat">
              <thead>
                <tr>
                  <th className="left">Person</th>
                  {board.weeks.map((w) => <th key={w}>{new Date(w + 'T00:00:00').toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}</th>)}
                  <th className="left">Now on</th>
                </tr>
              </thead>
              <tbody>
                {people.map((p) => (
                  <tr key={p.emp_id} title={p.skills.join(', ')}>
                    <td className="left">
                      <div className="strong small">{p.name}</div>
                      <div className="tiny muted">{p.title} · {p.office}</div>
                    </td>
                    {p.weekly.map((a, i) => {
                      const leave = isLeaveWeek(p, i)
                      return <td key={i} className={`cell ${cellClass(a, leave)}`}>{leave ? 'L' : a > 0 ? a : ''}</td>
                    })}
                    <td className="left tiny muted">
                      {p.assignments.filter((a) => a.kind === 'project').slice(0, 2).map((a) => `${a.project} (${a.allocation_pct}%, to ${fmtDate(a.to)})`).join(' · ') || <Pill tone="green">bench</Pill>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
