/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from 'react'
import { Lock } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Section, fmtDateTime } from '../lib'

export default function SettingsPage() {
  const { user } = useAuth()
  const [s, setS] = useState<any>(null)
  const [audit, setAudit] = useState<any[] | null>(null)
  useEffect(() => {
    api.get<any>('/api/settings').then(setS).catch(() => setS(null))
    if (user?.role === 'director') api.get<any[]>('/api/audit').then(setAudit).catch(() => setAudit([]))
  }, [user])
  if (!s) return <div className="page"><div className="empty"><span className="spinner" /></div></div>
  const p = s.pricing_policy
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Administration</div>
          <h1>Settings</h1>
          <div className="sub">The policies, approval rules and limits every agent and calculator works under.</div>
        </div>
      </div>
      <div className="notice blue small"><Lock size={15} /> Read-only. {s.note}</div>
      <div className="grid g2" style={{ alignItems: 'start' }}>
        <Section title="Pricing policy (enforced by code)">
          <table className="tbl"><tbody>
            <tr><td>Margin floor / target</td><td className="right">{p.margin_floor_pct}% / {p.target_margin_pct}%</td></tr>
            <tr><td>Discount without a Director</td><td className="right">up to {p.discount_without_director_pct}%</td></tr>
            <tr><td>Maximum discount</td><td className="right">{p.max_discount_pct}%</td></tr>
            <tr><td>Fixed-price risk premium</td><td className="right">{p.fixed_price_risk_premium_pct}%</td></tr>
            <tr><td>Contingency (low / medium / high risk)</td><td className="right">{p.contingency_pct.low}% / {p.contingency_pct.medium}% / {p.contingency_pct.high}%</td></tr>
            <tr><td>PM and tech-lead overhead</td><td className="right">{p.pm_overhead_pct}% + {p.lead_overhead_pct}%</td></tr>
            <tr><td>Minimum QA (share of dev hours)</td><td className="right">{p.min_qa_ratio_pct}%{p.regulated_qa_uplift_pct ? ` (+${p.regulated_qa_uplift_pct}% for regulated data)` : ''}</td></tr>
          </tbody></table>
        </Section>
        <Section title="Who approves what">
          <table className="tbl"><tbody>{s.approvals.map((a: any) => <tr key={a.what}><td>{a.what}</td><td>{a.who}</td></tr>)}</tbody></table>
          <div className="tiny muted" style={{ marginTop: 8 }}>Agents only draft. Nothing is sent to a client or an employee, no contract changes and no one is committed to a project without a person's approval.</div>
        </Section>
        <Section title="Spend and execution limits">
          <table className="tbl"><tbody>
            <tr><td>Model calls per run</td><td className="right">{s.limits.model_calls_per_run}</td></tr>
            <tr><td>Tool calls per run</td><td className="right">{s.limits.tool_calls_per_run}</td></tr>
            <tr><td>Tokens per run</td><td className="right">{s.limits.tokens_per_run.toLocaleString()}</td></tr>
            <tr><td>Daily AI budget (all users)</td><td className="right">USD {s.limits.daily_budget_usd}</td></tr>
            <tr><td>Deal runs per hour per computer</td><td className="right">{s.limits.deal_runs_per_hour_per_client}</td></tr>
            <tr><td>Longest client document</td><td className="right">{s.limits.max_document_chars.toLocaleString()} characters</td></tr>
          </tbody></table>
        </Section>
        <Section title="Model, data and roles">
          <table className="tbl"><tbody>
            <tr><td>Model</td><td className="mono">{s.model}</td></tr>
            <tr><td>Prices per 1M tokens</td><td>${s.prices_per_million_tokens_usd.input_per_m} input · ${s.prices_per_million_tokens_usd.cached_input_per_m} cached · ${s.prices_per_million_tokens_usd.output_per_m} output</td></tr>
            <tr><td>Company data</td><td>{s.data.synthetic ? <span className="sev amber">synthetic demo data</span> : 'company data'} as of {s.data.as_of}</td></tr>
            {Object.entries(s.roles).map(([k, v]) => <tr key={k}><td style={{ textTransform: 'capitalize' }}>{k}</td><td>{v as string}</td></tr>)}
          </tbody></table>
        </Section>
      </div>
      {audit && (
        <Section title={`Audit trail (${audit.length} most recent)`}>
          {audit.length === 0 && <div className="muted small">No decisions recorded yet.</div>}
          <table className="tbl"><tbody>{audit.map((a) => (
            <tr key={a.id}><td className="small nowrap">{fmtDateTime(a.ts)}</td><td className="small">{a.actor}<div className="tiny muted">{a.role}</div></td>
              <td className="small mono">{a.action}</td><td className="small">{a.summary}</td></tr>
          ))}</tbody></table>
        </Section>
      )}
    </div>
  )
}
