import { useEffect, useState, type ReactNode } from 'react'

// ------------------------------------------------------------------ tiny hash router

export function useRoute(): string[] {
  const read = () => window.location.hash.replace(/^#\/?/, '').split('?')[0].split('/').filter(Boolean)
  const [parts, setParts] = useState<string[]>(read)
  useEffect(() => {
    const on = () => setParts(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return parts
}

/** Query parameters after the hash route, e.g. #/deals?status=ready -> { status: 'ready' }. */
export function useHashParams(): Record<string, string> {
  const read = () => Object.fromEntries(new URLSearchParams(window.location.hash.split('?')[1] ?? ''))
  const [p, setP] = useState<Record<string, string>>(read)
  useEffect(() => {
    const on = () => setP(read())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return p
}

export const go = (path: string) => {
  window.location.hash = path
}

// ------------------------------------------------------------------ formatting

export const ROLE_LABEL: Record<string, string> = {
  pm: 'Project Manager',
  ba: 'Business Analyst',
  uiux: 'UI/UX Designer',
  fe: 'Frontend Dev',
  be: 'Backend Dev',
  mobile: 'Mobile Dev',
  qa: 'QA Engineer',
  devops: 'DevOps / Cloud',
  data: 'Data / BI',
  ml: 'AI / ML',
  lead: 'Tech Lead',
}

export const fmtInt = (n: number | null | undefined) => (n == null ? '–' : Math.round(n).toLocaleString('en-US'))
export const fmtMoney = (cur: string, n: number | null | undefined) =>
  n == null ? '–' : `${cur} ${Math.round(n).toLocaleString('en-US')}`
export const fmtUsd = (n: number | null | undefined, digits = 4) => (n == null ? '–' : `$${n.toFixed(digits)}`)
export const fmtK = (n: number | null | undefined) =>
  n == null ? '–' : n >= 1_000_000 ? `${(n / 1_000_000).toFixed(2)}M` : n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`
export const fmtDate = (iso: string | null | undefined) => {
  if (!iso) return '–'
  const d = new Date(iso.length === 10 ? iso + 'T00:00:00' : iso)
  return d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}
export const fmtDateTime = (iso: string) => {
  const d = new Date(iso)
  return d.toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
}

// ------------------------------------------------------------------ small components

export function Pill({ tone, children, pulse }: { tone?: string; children: ReactNode; pulse?: boolean }) {
  return (
    <span className={`pill ${tone ?? ''}`}>
      {pulse !== undefined && <span className={`dot ${pulse ? 'pulse' : ''}`} />}
      {children}
    </span>
  )
}

const STATUS: Record<string, [string, string]> = {
  queued: ['blue', 'Queued'],
  running: ['blue', 'Running'],
  ready: ['amber', 'Needs decision'],
  failed: ['red', 'Failed'],
  approved: ['green', 'Approved'],
  rejected: ['red', 'Rejected'],
  changes_requested: ['violet', 'Changes requested'],
  blocked: ['red', 'Blocked by safety filter'],
  needs_clarification: ['violet', 'Needs clarification'],
}

export function StatusPill({ status }: { status: string }) {
  const [tone, label] = STATUS[status] ?? ['', status]
  return (
    <Pill tone={tone} pulse={status === 'running' || status === 'queued'}>
      {label}
    </Pill>
  )
}

export function Stat({ label, value, foot, small }: { label: string; value: ReactNode; foot?: ReactNode; small?: boolean }) {
  return (
    <div className="card stat">
      <div className="label">{label}</div>
      <div className={`value ${small ? 'sm' : ''}`}>{value}</div>
      {foot && <div className="foot">{foot}</div>}
    </div>
  )
}

export function Bar({ value, max, tone }: { value: number; max: number; tone?: string }) {
  const pct = max > 0 ? Math.max(1, Math.min(100, (100 * value) / max)) : 0
  return (
    <div className="bar-track">
      <div className={`bar-fill ${tone ?? ''}`} style={{ width: `${pct}%` }} />
    </div>
  )
}

export function Section({ title, right, children }: { title: ReactNode; right?: ReactNode; children: ReactNode }) {
  return (
    <div className="card">
      <div className="card-head">
        <h3>{title}</h3>
        {right}
      </div>
      <div className="card-body">{children}</div>
    </div>
  )
}

export function List({ items, empty = 'None' }: { items: string[] | undefined; empty?: string }) {
  if (!items || items.length === 0) return <div className="muted small">{empty}</div>
  return (
    <ul style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>
      {items.map((x, i) => (
        <li key={i}>{x}</li>
      ))}
    </ul>
  )
}

export const sevTone = (s: string) => (s === 'high' ? 'red' : s === 'medium' || s === 'warning' ? 'amber' : 'blue')
