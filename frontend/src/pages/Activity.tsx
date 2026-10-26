/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from 'react'
import { ArrowLeft, ArrowRightLeft, Calculator, Check, Flag, LoaderCircle, RotateCcw, UserCheck } from 'lucide-react'
import { api } from '../api'
import { RunStatus } from '../cards'
import { List, Section, fmtDateTime, fmtUsd, go, useHashParams } from '../lib'

type Row = { id: string; module: string; module_label: string; title: string; status: string; raw_status: string; created_at: string
  trigger: string; agents: string[]; tool_calls: number; seconds: number | null; cost_usd: number | null; summary: string
  approval: string | null; approver: string | null; link: string; retryable: boolean; demo: boolean }

const STATUSES = ['all', 'running', 'awaiting_approval', 'needs_information', 'completed', 'failed', 'blocked']
const LABEL: Record<string, string> = { all: 'All', running: 'Running', awaiting_approval: 'Awaiting approval', needs_information: 'Needs information',
  completed: 'Completed', failed: 'Failed', blocked: 'Blocked' }

export default function ActivityPage({ id }: { id?: string }) {
  return id ? <RunDetail id={id} /> : <RunList />
}

function RunList() {
  const params = useHashParams()
  const [rows, setRows] = useState<Row[] | null>(null)
  const [mod, setMod] = useState(params.module ?? 'all')
  const [st, setSt] = useState(params.status ?? 'all')
  useEffect(() => { api.get<Row[]>('/api/activity').then(setRows).catch(() => setRows([])) }, [])
  const mods = ['all', ...Array.from(new Set((rows ?? []).map((r) => r.module)))]
  const shown = (rows ?? []).filter((r) => (mod === 'all' || r.module === mod) && (st === 'all' || r.status === st))
  const label = (m: string) => (m === 'all' ? 'All modules' : rows?.find((r) => r.module === m)?.module_label ?? m)
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Intelligence</div>
          <h1>Agent Activity</h1>
          <div className="sub">Every agent run across the platform: who or what triggered it, which agents and tools it used, how long it took,
            what it cost, what it found and whether a person has approved it. Open a run for its full collaboration trace.</div>
        </div>
      </div>
      <div className="row">{mods.map((m) => <button key={m} className={`btn btn-chip ${mod === m ? 'active-chip' : ''}`} onClick={() => setMod(m)}>{label(m)}</button>)}</div>
      <div className="row">{STATUSES.map((s) => <button key={s} className={`btn btn-chip ${st === s ? 'active-chip' : ''}`} onClick={() => setSt(s)}>{LABEL[s]}</button>)}</div>
      <div className="card">
        <table className="tbl">
          <thead><tr><th>Run</th><th>Status</th><th>Trigger</th><th>Agents · tools</th><th className="right">Time</th><th className="right">Cost</th><th>Approval</th></tr></thead>
          <tbody>
            {!rows && <tr><td colSpan={7}><div className="empty"><span className="spinner" /></div></td></tr>}
            {rows && shown.length === 0 && <tr><td colSpan={7}><div className="empty">No runs match.</div></td></tr>}
            {shown.map((r) => (
              <tr key={r.id} className="click" onClick={() => go(`/activity/${r.id}`)}>
                <td style={{ maxWidth: 380 }}><div className="act-mod">{r.module_label}{r.demo && <span className="pill blue" style={{ marginLeft: 6 }}>example</span>}</div>
                  <div className="strong small">{r.title}</div><div className="tiny muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.summary}</div></td>
                <td><RunStatus s={r.status} /></td>
                <td className="small">{r.trigger}<div className="tiny muted">{fmtDateTime(r.created_at)}</div></td>
                <td className="small">{r.agents.length} agents · {r.tool_calls} tools</td>
                <td className="right small">{r.seconds != null ? `${Math.round(r.seconds)} s` : '–'}</td>
                <td className="right small mono">{fmtUsd(r.cost_usd, 4)}</td>
                <td className="small">{r.approval ? <>{r.approval.replace('_', ' ')}<div className="tiny muted">{r.approver}</div></> : <span className="muted">–</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const FLOW_ICON: Record<string, typeof Check> = { agent_end: Check, handoff: ArrowRightLeft, calculator: Calculator, finding: Flag, status: UserCheck }

function buildFlow(r: any): { kind: string; label: string; text: string }[] {
  if (r.collaboration) return r.collaboration
  const labels: Record<string, string> = Object.fromEntries(Object.entries(r.steps ?? {}).map(([k, v]: any) => [k, v.label]))
  const out = (r.trace ?? []).filter((e: any) => ['agent_end', 'handoff', 'calculator', 'finding'].includes(e.kind))
    .map((e: any) => ({ kind: e.kind, label: labels[e.agent] ?? e.agent, text: e.text }))
  if (r.norm_status === 'awaiting_approval') out.push({ kind: 'status', label: 'People', text: 'Awaiting a person’s decision.' })
  if (r.decision) out.push({ kind: 'status', label: r.decision.approver, text: `Decision: ${String(r.decision.action).replace('_', ' ')}.` })
  return out
}

function RunDetail({ id }: { id: string }) {
  const [r, setR] = useState<any>(null)
  const [err, setErr] = useState<string | null>(null)
  const [showTrace, setShowTrace] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    let stop = false
    let t: number | undefined
    const load = async () => {
      try {
        const d = await api.get<any>(`/api/activity/${id}`)
        if (stop) return
        setR(d)
        if (['running', 'queued'].includes(d.status)) t = window.setTimeout(load, 1500)
      } catch (e) { if (!stop) setErr((e as Error).message) }
    }
    void load()
    return () => { stop = true; if (t) window.clearTimeout(t) }
  }, [id])
  if (err) return <div className="page"><div className="notice red">{err}</div></div>
  if (!r) return <div className="page"><div className="empty"><span className="spinner" /></div></div>
  const steps = Object.values(r.steps ?? {}) as any[]
  const flow = buildFlow(r)
  const findings = r.results?.findings ?? []
  const retry = async () => {
    setBusy(true)
    try { const n = await api.post<{ id: string }>(`/api/activity/${r.id}/retry`, {}); go(`/activity/${n.id}`) } catch (e) { setErr((e as Error).message) }
    setBusy(false)
  }
  const link = r.module === 'deal_desk' ? `#/deals/${r.id}` : r.module === 'scope_guard' ? `#/scope/${r.id}` : r.module === 'appraisals' ? `#/appraisals/${r.id}`
    : r.module === 'project_health' ? '#/projects' : r.module === 'bench' ? '#/bench' : r.module === 'deal_room' ? `#/deals/${r.input?.deal_id}` : null
  return (
    <div className="page">
      <div className="page-head">
        <div style={{ flex: 1 }}>
          <a href="#/activity" className="small muted row" style={{ gap: 4 }}><ArrowLeft size={14} /> Agent Activity</a>
          <h1 style={{ marginTop: 8 }}>{r.title}</h1>
          <div className="meta-line">
            <RunStatus s={r.norm_status} /><span className="act-mod">{r.module_label}</span><span>Started {fmtDateTime(r.created_at)} by <b>{r.created_by || r.input?.created_by || 'example run'}</b></span>
            {r.usage && <span><b>{(r.usage.input_tokens + r.usage.output_tokens).toLocaleString()}</b> tokens · <b>{fmtUsd(r.usage.cost_usd)}</b></span>}
            {link && <a href={link}>Open in {r.module_label}</a>}
          </div>
        </div>
        {['failed', 'blocked', 'interrupted'].includes(r.status) && ['deal_desk', 'project_health'].includes(r.module) && (
          <button className="btn" disabled={busy} onClick={retry}>{busy ? <LoaderCircle size={15} className="spin" /> : <RotateCcw size={15} />} Retry safely</button>
        )}
      </div>
      {r.error && <div className="notice red small"><b>Error:</b> {r.error}</div>}
      <div className="grid g2" style={{ alignItems: 'start' }}>
        <Section title="How the agents collaborated">
          {flow.length === 0 && <div className="muted small">No steps recorded yet.</div>}
          <div className="flow">
            {flow.map((f, i) => {
              const I = FLOW_ICON[f.kind] ?? Check
              return (
                <div key={i} className={`flow-item ${f.kind}`}>
                  <span className="flow-dot"><I size={11} strokeWidth={2.6} /></span>
                  <span className="flow-who">{f.label}</span>
                  <span className="flow-text">{f.text}</span>
                </div>
              )
            })}
          </div>
          <div className="tiny muted" style={{ marginTop: 10 }}>✓ agent finished · ⇄ work sent back to another agent · ⌗ number computed by code · ⚑ finding posted to the shared board</div>
        </Section>
        <div className="col" style={{ gap: 16 }}>
          <Section title="Steps">
            <table className="tbl"><thead><tr><th>Step</th><th>Status</th><th className="right">Rounds</th><th className="right">Time</th><th className="right">Cost</th></tr></thead>
              <tbody>{steps.map((s) => (
                <tr key={s.key}><td><div className="small strong">{s.label}</div><div className="tiny muted">{s.kind === 'code' ? 'code' : 'agent'}{s.summary ? ` · ${s.summary}` : ''}</div></td>
                  <td className="small">{s.status}</td><td className="right small">{s.rounds ?? '–'}</td><td className="right small">{s.seconds != null ? `${s.seconds}s` : '–'}</td>
                  <td className="right small mono">{s.usage ? fmtUsd(s.usage.cost_usd, 4) : '–'}</td></tr>
              ))}</tbody></table>
          </Section>
          {findings.length > 0 && (
            <Section title={`Findings passed between agents (${findings.length})`}>
              <div className="col" style={{ gap: 8 }}>{findings.map((f: any, i: number) => (
                <div key={i} className="small"><b>{f.from} → {f.to}</b> <span className={`sev ${f.severity === 'high' ? 'red' : f.severity === 'warning' ? 'amber' : 'neutral'}`}>{f.kind}</span>{f.pass > 1 && <span className="tiny muted"> · after re-run {f.pass - 1}</span>}
                  <div>{f.finding}</div><div className="tiny muted">Evidence: {f.evidence} · Action: {f.action}</div></div>
              ))}</div>
            </Section>
          )}
          {r.decision && <Section title="Human decision"><div className="small"><b>{String(r.decision.action).replace('_', ' ')}</b> by {r.decision.approver} on {fmtDateTime(r.decision.at)}{r.decision.note ? ` · “${r.decision.note}”` : ''}</div></Section>}
          {r.audit?.length > 0 && <Section title="Audit trail"><List items={r.audit.map((a: any) => `${fmtDateTime(a.ts)} · ${a.actor}: ${a.summary}`)} /></Section>}
        </div>
      </div>
      <Section title={`Full trace (${r.trace?.length ?? 0} events)`} right={<button className="btn btn-sm" onClick={() => setShowTrace((v) => !v)}>{showTrace ? 'Hide' : 'Show'}</button>}>
        {showTrace ? (
          <table className="tbl"><tbody>{(r.trace ?? []).map((e: any, i: number) => (
            <tr key={i}><td className="tiny muted mono">+{e.t}s</td><td className="small">{e.agent}</td><td className="small mono">{e.kind}</td>
              <td className="small" style={{ maxWidth: 640 }}>{e.text}{e.data ? <details><summary className="tiny muted">details</summary><pre className="tiny" style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(e.data, null, 1).slice(0, 2000)}</pre></details> : null}</td></tr>
          ))}</tbody></table>
        ) : <div className="small muted">Every tool call with its arguments and result, every hand-off and every guardrail event.</div>}
      </Section>
    </div>
  )
}
