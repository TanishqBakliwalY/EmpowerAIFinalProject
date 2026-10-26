import { useEffect, useState } from 'react'
import { ArrowRight, ChevronDown, ChevronRight, FilePlus2, Hourglass, ListChecks, Sparkles, TrendingUp } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { Columns, HBars, RecCard, RunStatus, type Rec } from '../cards'
import { useCopilot } from '../copilot'
import { BadgeShelf, Ring, type Badge } from '../fun'
import { fmtDate, fmtDateTime, fmtUsd, go } from '../lib'

type Kpi = { key: string; label: string; value: number | string; foot: string; link: string; tone: string; estimate?: boolean }
type ActivityRow = {
  id: string; module: string; module_label: string; title: string; status: string; created_at: string; trigger: string
  agents: string[]; tool_calls: number; seconds: number | null; cost_usd: number | null; summary: string; link: string
}
type HomeData = {
  as_of: string; synthetic: boolean; kpis: Kpi[]; actions: (Rec & { key: string; kind: string; impact_usd: number })[]
  ai_spend: { today_usd: number; budget_usd: number } | null
  outlook: {
    pipeline?: { note: string; rows: { label: string; count: number; usd: number }[] }
    delivery?: { note: string; counts: Record<string, number>; projects: { code: string; level: string; cpi: number | null; spi: number | null }[] }
    utilisation?: { note: string; weeks: string[]; pct: number[] }
    availability?: { note: string; weeks: string[]; count: number[] }
  }
  activity: ActivityRow[]
}

function greeting() {
  const h = new Date().getHours()
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}
const wk = (iso: string) => fmtDate(iso).replace(/ \d{4}$/, '')
const PIPE_TONE: Record<string, string> = { 'Awaiting decision': 'amber', Approved: 'green', Rejected: 'grey', 'Changes requested': '' }
const scrollToActions = () => document.getElementById('actions')?.scrollIntoView({ behavior: 'smooth' })

export default function HomePage() {
  const { user } = useAuth()
  const { setOpen } = useCopilot()
  const [h, setH] = useState<HomeData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [showReviewed, setShowReviewed] = useState(false)
  const load = () => api.get<HomeData>('/api/home').then(setH).catch((e) => setErr((e as Error).message))
  useEffect(() => { void load() }, [])
  if (!user) return null
  const first = user.name.split(' ')[0]
  const sales = user.role !== 'hr'
  const open = h?.actions.filter((a) => !a.review) ?? []
  const reviewed = h?.actions.filter((a) => a.review) ?? []

  return (
    <div className="page">
      <section className="hero v4">
        <div>
          <div className="tiny" style={{ color: '#9fb6e6', fontWeight: 500 }}>{user.role_label} · Empower Solutions{h?.synthetic ? ' · demo data (synthetic)' : ''}</div>
          <h1 style={{ marginTop: 4 }}>{greeting()}, {first}</h1>
          <p>
            {sales
              ? 'Your AI operations team has reviewed deals, delivery risks and staffing availability. Here are the decisions that need your attention.'
              : 'Your AI operations team has reviewed availability, the bench and the hike cycle. Here are the decisions that need your attention.'}
          </p>
        </div>
        <div className="row">
          {sales ? <button className="btn" onClick={() => go('/new')}><FilePlus2 size={16} /> New deal</button>
            : <button className="btn" onClick={() => go('/appraisals')}><TrendingUp size={16} /> Plan hikes</button>}
          {sales && <button className="btn btn-ghost" onClick={() => setOpen(true)}><Sparkles size={16} /> Ask Emi</button>}
          <button className="btn btn-ghost" onClick={scrollToActions}>
            <ListChecks size={16} /> Review {open.length || ''} pending decision{open.length === 1 ? '' : 's'}
          </button>
        </div>
      </section>

      {err && <div className="notice red small">{err}</div>}
      {!h && !err && <div className="card empty"><span className="spinner" /></div>}

      {h && (
        <div className="kpi-grid">
          {h.kpis.map((k) => (k.link.startsWith('#/home') ? (
            <button key={k.key} className={`kpi-card ${k.tone}`} style={{ textAlign: 'left', font: 'inherit', cursor: 'pointer' }} onClick={scrollToActions}>
              <span className="kpi-label">{k.label}{k.estimate && <span className="est-tag">estimate</span>}</span>
              <span className="kpi-value">{k.value}</span>
              <span className="kpi-foot">{k.foot}</span>
            </button>
          ) : (
            <a key={k.key} className={`kpi-card ${k.tone}`} href={k.link}>
              <span className="kpi-label">{k.label}{k.estimate && <span className="est-tag">estimate</span>}</span>
              <span className="kpi-value">{k.value}</span>
              <span className="kpi-foot">{k.foot}</span>
            </a>
          )))}
        </div>
      )}

      {h && (
        <div id="actions">
          <div className="section-head">
            <h2>Priority actions</h2>
            <span className="muted small">Ranked by severity, then value at stake. Accept or dismiss is recorded in the audit trail; the decision itself is made on the linked page.</span>
          </div>
          <div className="col" style={{ gap: 10 }}>
            {open.length === 0 && <div className="card empty">Nothing needs your attention right now.</div>}
            {open.slice(0, 8).map((a) => <RecCard key={a.key} r={a} onReviewed={load} />)}
            {open.length > 8 && <div className="small muted">{open.length - 8} more lower-priority item(s) in the modules and Agent Activity.</div>}
            {reviewed.length > 0 && (
              <button className="btn btn-ghost btn-sm" style={{ alignSelf: 'flex-start' }} onClick={() => setShowReviewed((v) => !v)}>
                {showReviewed ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Reviewed ({reviewed.length})
              </button>
            )}
            {showReviewed && reviewed.map((a) => <RecCard key={a.key} r={a} onReviewed={load} />)}
          </div>
        </div>
      )}

      {h && <Outlook o={h.outlook} />}

      {h && (
        <div className="card">
          <div className="card-head">
            <h3>Agent activity</h3>
            <a className="small" href="#/activity">All runs <ArrowRight size={13} style={{ verticalAlign: -2 }} /></a>
          </div>
          <div>
            {h.activity.length === 0 && <div className="empty">No agent runs yet.</div>}
            {h.activity.map((r) => (
              <a key={r.module + r.id} className="act-row" href={`#/activity/${r.id}`}>
                <span className="col" style={{ gap: 2 }}>
                  <span className="act-mod">{r.module_label}</span>
                  <span className="tiny muted">{fmtDateTime(r.created_at)}</span>
                </span>
                <span style={{ minWidth: 0 }}>
                  <span className="strong small" style={{ display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.title}</span>
                  <span className="act-sum" style={{ display: 'block' }}>
                    {r.trigger} · {r.agents.length} agent{r.agents.length === 1 ? '' : 's'} · {r.tool_calls} tool calls
                    {r.seconds != null ? ` · ${Math.round(r.seconds)} s` : ''}{r.summary ? ` · ${r.summary}` : ''}
                  </span>
                </span>
                <RunStatus s={r.status} />
              </a>
            ))}
          </div>
        </div>
      )}

      {h?.ai_spend && (
        <div className="small muted row" style={{ justifyContent: 'flex-end' }}>
          AI spend today {fmtUsd(h.ai_spend.today_usd, 3)} of {fmtUsd(h.ai_spend.budget_usd, 0)} daily budget · <a href="#/usage">Usage & safety</a>
        </div>
      )}
      <ProgressPanel />
    </div>
  )
}

function Outlook({ o }: { o: HomeData['outlook'] }) {
  return (
    <div>
      <div className="section-head">
        <h2>Business outlook</h2>
        <span className="muted small">Quotes and plans are labelled as such; nothing here is a revenue forecast.</span>
      </div>
      <div className="outlook">
        {o.pipeline && (
          <div className="panel">
            <h3>Sales pipeline <span className="est-tag">quoted value</span></h3>
            <HBars rows={o.pipeline.rows.map((r) => ({ label: `${r.label} (${r.count})`, value: r.usd, display: `USD ${Math.round(r.usd / 1000)}k`, tone: PIPE_TONE[r.label] }))} />
            <div className="panel-note">{o.pipeline.note}</div>
          </div>
        )}
        {o.delivery && (
          <div className="panel">
            <h3>Delivery risk <span className="est-tag">computed</span></h3>
            <HBars rows={[
              { label: 'Critical', value: o.delivery.counts.critical ?? 0, tone: 'red', display: `${o.delivery.counts.critical ?? 0} projects` },
              { label: 'Warning', value: o.delivery.counts.warning ?? 0, tone: 'amber', display: `${o.delivery.counts.warning ?? 0} projects` },
              { label: 'On track', value: o.delivery.counts.ok ?? 0, tone: 'green', display: `${o.delivery.counts.ok ?? 0} projects` },
            ]} />
            <div className="row" style={{ gap: 6 }}>
              {o.delivery.projects.filter((p) => p.level !== 'ok').map((p) => (
                <a key={p.code} href={`#/projects/${p.code}`} className={`sev ${p.level === 'critical' ? 'red' : 'amber'}`}>{p.code}{p.cpi != null ? ` · CPI ${p.cpi}` : ' · starting'}</a>
              ))}
            </div>
            <div className="panel-note">{o.delivery.note} CPI below 1 means effort is running ahead of progress.</div>
          </div>
        )}
        {o.utilisation && (
          <div className="panel">
            <h3>Utilisation, next 12 weeks <span className="est-tag">plan</span></h3>
            <Columns values={o.utilisation.pct} labels={o.utilisation.weeks.map(wk)} max={100} unit="%" />
            <div className="panel-note">{o.utilisation.note}</div>
          </div>
        )}
        {o.availability && (
          <div className="panel">
            <h3>People available (50%+ free) <span className="est-tag">plan</span></h3>
            <Columns values={o.availability.count} labels={o.availability.weeks.map(wk)} tone="green" />
            <div className="panel-note">{o.availability.note} <a href="#/bench">Plan the bench <Hourglass size={11} style={{ verticalAlign: -1 }} /></a></div>
          </div>
        )}
      </div>
    </div>
  )
}

type Progress = { goals: { key: string; label: string; value: number; goal: number }[]; badges: Badge[] }
const GOAL_COLOR: Record<string, string> = { decided: '#1a66d9', rehearsals: '#7a5af8', hours: '#12a150' }

function ProgressPanel() {
  const [open, setOpen] = useState(false)
  const [p, setP] = useState<Progress | null>(null)
  useEffect(() => {
    if (open && !p) api.get<Progress>('/api/me/progress').then(setP).catch(() => {})
  }, [open, p])
  return (
    <div className="card">
      <button className="card-head" style={{ width: '100%', border: 'none', background: 'transparent', cursor: 'pointer', font: 'inherit' }} onClick={() => setOpen((v) => !v)}>
        <h3 className="row" style={{ gap: 6 }}>{open ? <ChevronDown size={15} /> : <ChevronRight size={15} />} Your progress</h3>
        <span className="tiny muted">optional: weekly goals and badges for good habits (rehearsing calls, logging impact, deciding scope)</span>
      </button>
      {open && p && (
        <div className="card-body row" style={{ gap: 28, alignItems: 'flex-start' }}>
          {p.goals.map((g) => (
            <div key={g.key} className="row" style={{ gap: 10 }}>
              <Ring value={g.value} max={g.goal} color={GOAL_COLOR[g.key] ?? '#1a66d9'} size={52} stroke={6}><b>{Number.isInteger(g.value) ? g.value : g.value.toFixed(1)}</b></Ring>
              <div><div className="small strong">{g.label}</div><div className="tiny muted">goal {g.goal}</div></div>
            </div>
          ))}
          <div style={{ flex: 1, minWidth: 280 }}><BadgeShelf badges={p.badges} /></div>
        </div>
      )}
    </div>
  )
}
