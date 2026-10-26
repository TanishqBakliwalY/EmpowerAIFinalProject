import { useEffect, useState } from 'react'
import { api } from '../api'
import { Bar, Pill, Section, Stat, fmtDateTime, fmtInt, fmtK, fmtUsd, sevTone } from '../lib'
import type { Meta, SafetyEvent, UsageReport } from '../types'

const AGENT_LABEL: Record<string, string> = {
  analyst: 'Requirements Analyst',
  architect: 'Solution Architect',
  estimator: 'Estimator',
  staffing: 'Staffing Planner',
  pricing: 'Pricing Strategist',
  critic: 'Deal Critic',
  writer: 'Proposal Writer',
  assistant: 'Staffing Assistant',
  copilot: 'Emi (copilot)',
}

export default function UsagePage({ meta }: { meta: Meta | null }) {
  const [u, setU] = useState<UsageReport | null>(null)
  const [ev, setEv] = useState<SafetyEvent[]>([])
  useEffect(() => {
    api.get<UsageReport>('/api/usage').then(setU)
    api.get<SafetyEvent[]>('/api/safety-events').then(setEv)
  }, [])
  if (!u) return <div className="page"><div className="empty"><span className="spinner" /></div></div>

  const t = u.totals
  const dealRuns = u.by_agent.filter((a) => a.module === 'deal_desk').reduce((m, a) => Math.max(m, a.runs), 0)
  const dealCost = u.by_agent.filter((a) => a.module === 'deal_desk').reduce((s, a) => s + a.cost_usd, 0)
  const perDeal = dealRuns ? dealCost / dealRuns : 0
  const maxAgentCost = Math.max(...u.by_agent.map((a) => a.cost_usd), 1e-9)
  const cacheHit = t.input_tokens ? (100 * t.cached_tokens) / t.input_tokens : 0
  const p = u.prices_per_million_tokens_usd

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Usage & safety</h1>
          <div className="sub">Measured token use and cost from real runs, the limits that cap spending, and every safety event the guards recorded.</div>
        </div>
      </div>

      <div className="grid g4">
        <Stat label="AI runs" value={fmtInt(t.runs)} foot={`${dealRuns} deals · ${t.runs - dealRuns} other (Emi messages, rehearsals, staffing questions, backtests)`} />
        <Stat label="Tokens" value={fmtK(t.input_tokens + t.output_tokens)} foot={`${fmtK(t.input_tokens)} in (${cacheHit.toFixed(0)}% cached) · ${fmtK(t.output_tokens)} out`} />
        <Stat label="Average cost per deal" value={fmtUsd(perDeal, 3)} foot="all 7 agents, incl. revisions" />
        <Stat label="Spent today" value={fmtUsd(u.spent_today_usd, 3)} foot={<>budget {fmtUsd(u.daily_budget_usd, 2)}/day <Bar value={u.spent_today_usd} max={u.daily_budget_usd} /></>} />
      </div>

      <div className="grid g2">
        <Section title="Cost by agent (all runs)">
          <table className="tbl">
            <thead><tr><th>Agent</th><th className="num">Runs</th><th className="num">Input</th><th className="num">Cached</th><th className="num">Output</th><th className="num">Cost</th><th style={{ width: 110 }}></th></tr></thead>
            <tbody>
              {u.by_agent.map((a) => (
                <tr key={a.module + a.agent}>
                  <td>
                    <span className="strong">{AGENT_LABEL[a.agent] ?? a.agent}</span>{' '}
                    {a.module !== 'deal_desk' && <Pill tone={a.module === 'backtest' ? 'violet' : a.module === 'copilot' ? 'green' : 'blue'}>{a.module}</Pill>}
                  </td>
                  <td className="num">{a.runs}</td>
                  <td className="num">{fmtK(a.input_tokens)}</td>
                  <td className="num">{fmtK(a.cached_tokens)}</td>
                  <td className="num">{fmtK(a.output_tokens)}</td>
                  <td className="num">{fmtUsd(a.cost_usd, 4)}</td>
                  <td><Bar value={a.cost_usd} max={maxAgentCost} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Section>
        <Section title="Prices and spending limits">
          <dl className="kv">
            <dt>Model</dt><dd className="mono">{meta?.model}</dd>
            <dt>Input</dt><dd className="mono">${p.input_per_m} / 1M tokens</dd>
            <dt>Cached input</dt><dd className="mono">${p.cached_input_per_m} / 1M tokens</dd>
            <dt>Output</dt><dd className="mono">${p.output_per_m} / 1M tokens</dd>
            {meta && (
              <>
                <dt>Per run</dt><dd>{meta.limits.requests_per_run} model calls, {meta.limits.tool_calls_per_run} tool calls, {fmtK(meta.limits.tokens_per_run)} tokens</dd>
                <dt>Per day</dt><dd>{fmtUsd(meta.limits.daily_budget_usd, 2)} across all users; new runs pause when reached</dd>
                <dt>Per user</dt><dd>8 deal runs and 40 staffing questions per hour</dd>
                <dt>Input size</dt><dd>{meta.limits.max_brief_chars.toLocaleString()} characters per client document</dd>
              </>
            )}
          </dl>
          <div className="notice small" style={{ marginTop: 12 }}>
            Cost-cutting built in: long static prompts first + a prompt-cache key per agent (cached input is billed at 10%), low reasoning effort
            everywhere except the Deal Critic (backtested: same accuracy, 30% cheaper and 37% faster), compact JSON hand-offs, and tools that return only the top matches.
          </div>
        </Section>
      </div>

      <Section title="Reviewer feedback (impact evidence)">
        {!u.feedback || u.feedback.reviews === 0 ? (
          <div className="muted small">
            No feedback yet. When you approve or reject a deal, add how many hours that quote takes by hand and a 1–5 quality score;
            the totals appear here.
          </div>
        ) : (
          <div className="col">
            <div className="grid g4">
              <Stat label="Deals reviewed" value={u.feedback.reviews} small />
              <Stat label="Average draft quality" value={u.feedback.avg_quality != null ? `${u.feedback.avg_quality}/5` : '–'} small />
              <Stat label="Manual time (reviewer estimate)" value={`${u.feedback.manual_hours_total} h`} small />
              <Stat label="Time saved" value={u.feedback.hours_saved_total != null ? `${u.feedback.hours_saved_total} h` : '–'} small foot={`app time ${u.feedback.app_hours_total} h`} />
            </div>
            <table className="tbl">
              <thead><tr><th>Deal</th><th>Reviewer</th><th>Decision</th><th className="num">Manual h</th><th className="num">App min</th><th className="num">Quality</th><th>Note</th></tr></thead>
              <tbody>
                {u.feedback.rows.map((r) => (
                  <tr key={r.deal_id}>
                    <td><a href={`#/deals/${r.deal_id}`}>{r.title}</a></td><td>{r.approver}</td><td>{r.action}</td>
                    <td className="num">{r.manual_hours ?? '–'}</td><td className="num">{r.app_minutes}</td><td className="num">{r.quality ?? '–'}</td>
                    <td className="small muted">{r.note}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Daily usage">
        <table className="tbl">
          <thead><tr><th>Day (UTC)</th><th className="num">Runs</th><th className="num">Input</th><th className="num">Cached</th><th className="num">Output</th><th className="num">Cost</th></tr></thead>
          <tbody>
            {u.by_day.map((d) => (
              <tr key={d.day}><td>{d.day}</td><td className="num">{d.runs}</td><td className="num">{fmtK(d.input_tokens)}</td><td className="num">{fmtK(d.cached_tokens)}</td><td className="num">{fmtK(d.output_tokens)}</td><td className="num">{fmtUsd(d.cost_usd, 4)}</td></tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title={`Safety events (${ev.length})`}>
        {ev.length === 0 ? (
          <div className="muted small">No safety events yet. Try the “Security test” sample on the New deal page.</div>
        ) : (
          <table className="tbl">
            <thead><tr><th>When</th><th>Severity</th><th>Guard</th><th>What happened</th><th>Run</th></tr></thead>
            <tbody>
              {ev.map((e) => (
                <tr key={e.id}>
                  <td className="small nowrap muted">{fmtDateTime(e.ts)}</td>
                  <td><Pill tone={sevTone(e.severity)}>{e.severity}</Pill></td>
                  <td className="mono small">{e.kind}</td>
                  <td className="small">
                    {e.message}
                    {(e.detail as { snippet?: string } | null)?.snippet && <div className="tiny muted mono">“{(e.detail as { snippet: string }).snippet}”</div>}
                  </td>
                  <td className="small">{e.run_id ? <a href={`#/deals/${e.run_id}`} className="mono">{e.run_id}</a> : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  )
}
