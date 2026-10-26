// Shared building blocks for findings and recommendations: one card layout, status and severity badges that never
// rely on colour alone (each has an icon and a word), and two small SVG charts.
import { useState, type ReactNode } from 'react'
import {
  Ban, CircleCheck, CircleHelp, CircleX, Clock, Info, LoaderCircle, OctagonAlert, TriangleAlert, UserCheck,
} from 'lucide-react'
import { api } from './api'

export type Severity = 'critical' | 'warning' | 'info' | 'ok'

const SEV: Record<Severity, [string, string, typeof Info]> = {
  critical: ['red', 'Critical', OctagonAlert],
  warning: ['amber', 'Warning', TriangleAlert],
  info: ['neutral', 'Info', Info],
  ok: ['green', 'On track', CircleCheck],
}

export function SeverityBadge({ s }: { s: string }) {
  const [tone, label, Icon] = SEV[(s as Severity) in SEV ? (s as Severity) : 'info']
  return <span className={`sev ${tone}`}><Icon size={12} strokeWidth={2.4} />{label}</span>
}

const RUN: Record<string, [string, string, typeof Info]> = {
  queued: ['neutral', 'Queued', Clock],
  running: ['blue', 'Running', LoaderCircle],
  completed: ['green', 'Completed', CircleCheck],
  awaiting_approval: ['amber', 'Awaiting approval', UserCheck],
  needs_information: ['violet', 'Needs information', CircleHelp],
  blocked: ['red', 'Blocked', Ban],
  failed: ['red', 'Failed', CircleX],
}

export function RunStatus({ s }: { s: string }) {
  const [tone, label, Icon] = RUN[s] ?? ['neutral', s, Info]
  return <span className={`sev ${tone}`}><Icon size={12} strokeWidth={2.4} className={s === 'running' ? 'spin' : ''} />{label}</span>
}

export type Rec = {
  key?: string
  severity: string
  title: string
  finding: string
  evidence?: string[]
  impact?: string
  recommendation?: string
  confidence?: { label: string; why: string }
  agent?: string
  link?: string
  action_label?: string
  urgency?: string
  review?: { status: string; by: string; at: string; note?: string } | null
}

/** Finding, evidence, impact, recommendation, confidence and actions, in that order, for every agent finding. */
export function RecCard({ r, onReviewed, extra }: { r: Rec; onReviewed?: () => void; extra?: ReactNode }) {
  const [busy, setBusy] = useState(false)
  const review = async (status: string) => {
    if (!r.key) return
    const note = status === 'dismissed' ? window.prompt('Why dismiss it? (recorded in the audit trail)') ?? '' : ''
    if (status === 'dismissed' && note === null) return
    setBusy(true)
    await api.post(`/api/recommendations/${encodeURIComponent(r.key)}/review`, { status, note }).catch(() => {})
    setBusy(false)
    onReviewed?.()
  }
  return (
    <div className={`rec ${r.severity} ${r.review ? 'reviewed' : ''}`}>
      <div className="rec-head">
        <SeverityBadge s={r.severity} />
        <div className="rec-title">{r.link ? <a href={r.link}>{r.title}</a> : r.title}</div>
        {r.urgency && <span className="rec-urgency">{r.urgency}</span>}
      </div>
      <div className="rec-grid">
        <div className="rec-label">Finding</div><div>{r.finding}</div>
        {r.evidence && r.evidence.length > 0 && (<><div className="rec-label">Evidence</div>
          <div><ul className="rec-ev">{r.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul></div></>)}
        {r.impact && (<><div className="rec-label">Impact</div><div>{r.impact}</div></>)}
        {r.recommendation && (<><div className="rec-label">Recommendation</div><div className="strong-ish">{r.recommendation}</div></>)}
        {r.confidence && (<><div className="rec-label">Confidence</div><div><b>{r.confidence.label}.</b> <span className="muted">{r.confidence.why}</span></div></>)}
      </div>
      {extra}
      <div className="rec-foot">
        {r.agent && <span className="tiny muted">From: {r.agent}</span>}
        <span className="spacer" />
        {r.review ? (
          <span className="tiny muted">
            {r.review.status === 'accepted' ? 'Accepted' : 'Dismissed'} by <b>{r.review.by}</b>
            {r.review.note ? ` (“${r.review.note}”)` : ''}
            {r.key && <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => review('open')}>Reopen</button>}
          </span>
        ) : (
          <>
            {r.link && <a className="btn btn-sm btn-primary" href={r.link}>{r.action_label ?? 'Open the analysis'}</a>}
            {r.key && <button className="btn btn-sm" disabled={busy} onClick={() => review('accepted')}>Accept</button>}
            {r.key && <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => review('dismissed')}>Dismiss</button>}
          </>
        )}
      </div>
    </div>
  )
}

/** Horizontal bars with a value label; for small categorical series. */
export function HBars({ rows, unit = '' }: { rows: { label: string; value: number; display?: string; tone?: string }[]; unit?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value))
  return (
    <div className="hbars">
      {rows.map((r) => (
        <div className="hbar" key={r.label}>
          <span className="hbar-label">{r.label}</span>
          <span className="hbar-track"><span className={`hbar-fill ${r.tone ?? ''}`} style={{ width: `${Math.max(2, (100 * r.value) / max)}%` }} /></span>
          <span className="hbar-val">{r.display ?? `${r.value}${unit}`}</span>
        </div>
      ))}
    </div>
  )
}

/** Vertical column chart over weeks (values with labels underneath). */
export function Columns({ values, labels, max, unit = '', tone = 'blue' }: { values: number[]; labels: string[]; max?: number; unit?: string; tone?: string }) {
  const m = max ?? Math.max(1, ...values)
  return (
    <div className="cols">
      {values.map((v, i) => (
        <div className="col-item" key={i} title={`${labels[i]}: ${v}${unit}`}>
          <span className="col-val">{v}{unit}</span>
          <span className="col-bar"><span className={`col-fill ${tone}`} style={{ height: `${Math.max(3, (100 * v) / m)}%` }} /></span>
          <span className="col-label">{labels[i]}</span>
        </div>
      ))}
    </div>
  )
}
