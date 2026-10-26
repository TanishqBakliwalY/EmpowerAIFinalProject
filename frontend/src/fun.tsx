// A light game layer: a deal-health score, progress rings, badges and a small celebration on approval.
// Everything is computed from real data; nothing here changes what the agents or calculators do.
import type { ReactNode } from 'react'
import type { Deal } from './types'

type Factor = { label: string; points: number }

export function dealHealth(deal: Deal): { score: number; factors: Factor[] } {
  const r = deal.results
  const q = r.quote
  const factors: Factor[] = []
  if (q) {
    const m = q.recommended_model === 'fixed' ? q.margin_pct_fixed : q.margin_pct_tm
    if (m < q.margin_floor_pct) factors.push({ label: 'Margin below the floor', points: -40 })
    else if (m < q.target_margin_pct) factors.push({ label: 'Margin under target', points: -10 })
    else factors.push({ label: 'Margin at or above target', points: 0 })
    if (q.budget_fit && /above/i.test(q.budget_fit)) factors.push({ label: "Above the client's budget", points: -15 })
    if (q.needs_approval) factors.push({ label: 'Needs a Director', points: -5 })
  }
  if (r.schedule?.meets_deadline === false) factors.push({ label: 'Misses the deadline', points: -15 })
  const v = r.review?.verdict
  if (v === 'revise') factors.push({ label: 'Critic: revise', points: -10 })
  if (v === 'escalate') factors.push({ label: 'Critic: escalate', points: -20 })
  const risk = r.estimate?.risk_level
  if (risk === 'high') factors.push({ label: 'High delivery risk', points: -10 })
  if (risk === 'medium') factors.push({ label: 'Medium delivery risk', points: -5 })
  if ((r.leak_findings ?? []).length > 0) factors.push({ label: 'Leak guard redacted lines', points: -20 })
  if (r.phase1) factors.push({ label: 'Phase 1 fallback ready', points: +5 })
  const score = Math.max(0, Math.min(100, 100 + factors.reduce((a, f) => a + f.points, 0)))
  return { score, factors: factors.filter((f) => f.points !== 0) }
}

export function Ring({ value, max = 100, size = 64, stroke = 7, color, children }: {
  value: number; max?: number; size?: number; stroke?: number; color: string; children?: ReactNode
}) {
  const rad = (size - stroke) / 2
  const circ = 2 * Math.PI * rad
  const pct = max > 0 ? Math.max(0, Math.min(1, value / max)) : 0
  return (
    <div className="ring" style={{ width: size, height: size }}>
      <svg width={size} height={size}>
        <circle cx={size / 2} cy={size / 2} r={rad} stroke="var(--surface-3)" strokeWidth={stroke} fill="none" />
        {pct > 0 && (
          <circle cx={size / 2} cy={size / 2} r={rad} stroke={color} strokeWidth={stroke} fill="none" strokeLinecap="round"
            strokeDasharray={`${circ * pct} ${circ}`} transform={`rotate(-90 ${size / 2} ${size / 2})`} className="ring-fill" />
        )}
      </svg>
      <div className="ring-center">{children}</div>
    </div>
  )
}

const healthTone = (s: number) => (s >= 80 ? ['var(--green)', 'Strong'] : s >= 60 ? ['#2e90fa', 'Workable'] : s >= 40 ? ['#f79009', 'At risk'] : ['var(--red)', 'Weak'])

export function HealthRing({ deal }: { deal: Deal }) {
  const { score, factors } = dealHealth(deal)
  const [color, label] = healthTone(score)
  return (
    <div className="card health">
      <Ring value={score} color={color} size={72} stroke={8}><b>{score}</b></Ring>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="row" style={{ gap: 8 }}>
          <span className="strong">Deal health: {label}</span>
          <span className="tiny muted">from margin, budget fit, deadline, the critic's verdict, risk and the leak guard</span>
        </div>
        <div className="row" style={{ gap: 6, marginTop: 8 }}>
          {factors.length === 0 && <span className="pill green">Nothing holding this deal back</span>}
          {factors.map((f) => (
            <span key={f.label} className={`pill ${f.points > 0 ? 'green' : f.points <= -15 ? 'red' : 'amber'}`}>
              {f.label} {f.points > 0 ? `+${f.points}` : f.points}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

const COLORS = ['#1285e9', '#12a150', '#f79009', '#7a5af8', '#ee46bc', '#0037bf']

export function Confetti() {
  // 28 pieces, pure CSS; hidden for people who prefer reduced motion (see styles.css).
  return (
    <div className="confetti" aria-hidden>
      {Array.from({ length: 28 }, (_, i) => (
        <span key={i} style={{
          left: `${(i * 37) % 100}%`, background: COLORS[i % COLORS.length],
          animationDelay: `${(i % 7) * 0.04}s`, ['--dx' as string]: `${((i * 53) % 120) - 60}px`,
          ['--rot' as string]: `${(i * 97) % 360}deg`,
        }} />
      ))}
    </div>
  )
}

export type Badge = { key: string; label: string; hint: string; earned: boolean }

export function BadgeShelf({ badges }: { badges: Badge[] }) {
  return (
    <div className="badges">
      {badges.map((b) => (
        <div key={b.key} className={`badge ${b.earned ? 'earned' : ''}`} title={b.hint}>
          <span className="badge-medal">{b.earned ? '★' : '☆'}</span>
          <span className="badge-label">{b.label}</span>
        </div>
      ))}
    </div>
  )
}
