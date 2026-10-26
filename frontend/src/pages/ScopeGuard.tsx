import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Mail, Minus, Paperclip, Ticket, TriangleAlert, X } from 'lucide-react'
import { api } from '../api'
import { ACCEPT, uploadDocument } from '../files'
import { Pill, Section, Stat, StatusPill, fmtDateTime, fmtInt, fmtMoney, fmtUsd, go, sevTone, useRoute, useHashParams } from '../lib'
import { Markdown } from '../markdown'
import type { Attachment, Finding, Step, Usage } from '../types'

// ------------------------------------------------------------------ types (this module only)

type Clause = { id: string; type: string; title: string; text: string }
type Sow = {
  sow_id: string
  project_code: string
  project_name: string
  client: string
  client_country: string
  contract_type: string
  currency: string
  contract_value: number | null
  start_date: string | null
  end_date: string | null
  warranty_days: number | null
  source: 'seed' | 'deal'
  deal_id?: string
  cr_rates: Record<string, number>
  clauses: Clause[]
}
type SowSummary = Omit<Sow, 'cr_rates' | 'clauses'> & { clause_counts: Record<string, number> }
type Sample = { id: string; sow_id: string; channel: string; from: string; subject: string; text: string }
type Item = {
  ask_id: string
  quote: string
  summary: string
  kind: string
  verdict: Verdict
  model_verdict: Verdict | null
  clause_ids: string[]
  invalid_clause_ids: string[]
  reasoning: string
  confidence: string
  question_for_client: string | null
  downgraded: boolean
  downgrade_reason: string | null
}
type Verdict = 'in_scope' | 'out_of_scope' | 'ambiguous' | 'warranty_fix'
type CR = {
  ask_id: string
  summary: string
  hours_by_role: Record<string, number>
  build_hours: number
  pm_hours: number
  total_hours: number
  price: number
  currency: string
  basis: string
  assumptions: string[]
  estimated: boolean
}
type Pricing = { currency: string; items: CR[]; total_hours: number; total_price: number; counts: Record<string, number>; warnings: string[] }
type Analysis = {
  id: string
  status: string
  created_at: string
  title: string
  created_by?: string
  input: { sow_id: string; subject: string | null; message: string; source: string }
  steps: Record<string, Step>
  usage?: Usage
  screen: { findings: Finding[]; injection_suspected?: boolean; removed_lines?: number }
  results: {
    items?: Item[]
    pricing?: Pricing
    reply_draft?: { subject: string; body: string }
    reply_text?: string
    leak_findings?: Finding[]
  }
  decision: { action: string; absorb_ask_ids: string[]; note: string; approver: string; at: string } | null
  error: string | null
}
type AnalysisRow = {
  id: string
  title: string
  status: string
  created_at: string
  sow_id: string
  subject: string | null
  asks: number
  counts: Record<string, number> | null
  cr_total: number | null
  currency: string | null
  decision: string | null
  cost_usd: number | null
  flags: number
}
type LedgerRow = {
  sow_id: string
  project_name: string
  client: string
  currency: string
  analyses: number
  approved: number
  asks: number
  in_scope: number
  warranty_fix: number
  ambiguous: number
  out_of_scope: number
  billable_hours: number
  billable_value: number
  absorbed_hours: number
  absorbed_value: number
  margin_protected: number
}
type Ledger = { projects: LedgerRow[]; totals: { analyses: number; approved: number; out_of_scope_asks: number; billable_hours: number; absorbed_hours: number } }
type DealRow = { id: string; title: string; status: string }

const VERDICT: Record<Verdict, [string, string]> = {
  in_scope: ['green', 'In scope'],
  warranty_fix: ['blue', 'Warranty fix'],
  out_of_scope: ['amber', 'Change request'],
  ambiguous: ['violet', 'Ask the client'],
}
const CLAUSE_GROUPS: [string, string][] = [
  ['in_scope', 'In scope'],
  ['out_of_scope', 'Out of scope'],
  ['assumption', 'Assumptions'],
  ['warranty', 'Warranty'],
  ['change_control', 'Change control'],
]
const STEP_TONE: Record<string, string> = { done: 'green', running: 'blue', failed: 'red', skipped: '', pending: '' }
const isRunId = (s: string | undefined) => !!s && /^[0-9a-f]{10}$/.test(s)

export default function ScopeGuard() {
  const route = useRoute()
  const routeRun = isRunId(route[1]) ? route[1] : null
  const [sows, setSows] = useState<SowSummary[]>([])
  const [sowId, setSowId] = useState<string>('')
  const [sow, setSow] = useState<Sow | null>(null)
  const [samples, setSamples] = useState<Sample[]>([])
  const [runs, setRuns] = useState<AnalysisRow[]>([])
  const [ledger, setLedger] = useState<Ledger | null>(null)
  const pendingOnly = useHashParams().status === 'pending'
  const [runId, setRunId] = useState<string | null>(routeRun)
  const [reload, setReload] = useState(0)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => setRunId(routeRun), [routeRun])

  useEffect(() => {
    api.get<SowSummary[]>('/api/scope/sows').then((s) => {
      setSows(s)
      setSowId((cur) => cur || s[0]?.sow_id || '')
    }).catch((e) => setErr((e as Error).message))
  }, [reload])

  useEffect(() => {
    if (!sowId) return
    api.get<Sow>(`/api/scope/sows/${sowId}`).then(setSow).catch(() => setSow(null))
    api.get<Sample[]>(`/api/scope/samples?sow_id=${sowId}`).then(setSamples).catch(() => setSamples([]))
  }, [sowId])

  useEffect(() => {
    api.get<AnalysisRow[]>('/api/scope/analyses').then(setRuns).catch(() => setRuns([]))
    api.get<Ledger>('/api/scope/ledger').then(setLedger).catch(() => setLedger(null))
  }, [reload, runId])

  const open = (id: string) => {
    setRunId(id)
    go(`/scope/${id}`)
  }

  const t = ledger?.totals
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Delivery</div>
          <h1>Scope-Creep Guard</h1>
          <div className="sub">
            Paste a client's email or ticket. Agents split it into asks and check each against the signed SOW, citing clauses.
            Extra work becomes a change request priced at the SOW's own rates, with a reply drafted for you to approve.
          </div>
        </div>
      </div>

      {err && <div className="notice red small">{err}</div>}

      <div className="grid g4">
        <Stat label="Messages checked" value={fmtInt(t?.analyses ?? 0)} foot={`${t?.approved ?? 0} approved`} />
        <Stat label="Change requests found" value={fmtInt(t?.out_of_scope_asks ?? 0)} foot="in approved checks" />
        <Stat label="Billable CR hours" value={fmtInt(t?.billable_hours ?? 0)} foot="would otherwise be absorbed" />
        <Stat label="Absorbed as goodwill" value={`${fmtInt(t?.absorbed_hours ?? 0)} h`} foot="a person's choice, logged" />
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.25fr)' }}>
        <SowPanel sows={sows} sowId={sowId} setSowId={setSowId} sow={sow} onCreated={(id) => { setReload((r) => r + 1); setSowId(id) }} />
        <MessagePanel sow={sow} samples={samples} onStarted={(id) => { open(id); setReload((r) => r + 1) }} />
      </div>

      {runId && <AnalysisView id={runId} onChanged={() => setReload((r) => r + 1)} />}

      <Section title={pendingOnly ? 'Checks waiting for a decision or the client' : 'Recent checks'} right={pendingOnly ? <a className="small" href="#/scope">Show all</a> : undefined}>
        {runs.length === 0 ? (
          <div className="muted small">No messages checked yet. Pick a sample on the right and press “Check against SOW”.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr><th>Message</th><th>Status</th><th className="num">Asks</th><th>Verdicts</th><th className="num">CR value</th><th>Decision</th><th className="num">AI cost</th><th>When</th></tr>
            </thead>
            <tbody>
              {runs.filter((r) => !pendingOnly || ['ready', 'needs_clarification'].includes(r.status)).map((r) => (
                <tr key={r.id} className="click" onClick={() => open(r.id)} style={{ cursor: 'pointer' }}>
                  <td><div className="strong">{r.title}</div><div className="tiny muted">{r.sow_id}</div></td>
                  <td><StatusPill status={r.status} /></td>
                  <td className="num">{r.asks}</td>
                  <td className="small">
                    {r.counts ? Object.entries(r.counts).filter(([, n]) => n > 0).map(([v, n]) => (
                      <Pill key={v} tone={VERDICT[v as Verdict]?.[0]}>{n} {VERDICT[v as Verdict]?.[1] ?? v}</Pill>
                    )) : '–'}
                    {r.flags > 0 && <Pill tone="red"><TriangleAlert size={12} /> {r.flags}</Pill>}
                  </td>
                  <td className="num">{r.cr_total ? fmtMoney(r.currency ?? '', r.cr_total) : '–'}</td>
                  <td>{r.decision ?? '–'}</td>
                  <td className="num">{fmtUsd(r.cost_usd)}</td>
                  <td className="small muted">{fmtDateTime(r.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title="Scope ledger (approved checks)">
        {!ledger || ledger.projects.length === 0 ? (
          <div className="muted small">Nothing approved yet.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr><th>Project</th><th className="num">Checked</th><th className="num">In scope</th><th className="num">Warranty</th><th className="num">Ask client</th><th className="num">Change req.</th><th className="num">Billable</th><th className="num">Absorbed</th></tr>
            </thead>
            <tbody>
              {ledger.projects.map((p) => (
                <tr key={p.sow_id}>
                  <td><div className="strong">{p.project_name}</div><div className="tiny muted">{p.client} · {p.sow_id}</div></td>
                  <td className="num">{p.approved}/{p.analyses}</td>
                  <td className="num">{p.in_scope}</td>
                  <td className="num">{p.warranty_fix}</td>
                  <td className="num">{p.ambiguous}</td>
                  <td className="num">{p.out_of_scope}</td>
                  <td className="num">{fmtInt(p.billable_hours)} h · {fmtMoney(p.currency, p.billable_value)}</td>
                  <td className="num">{fmtInt(p.absorbed_hours)} h · {fmtMoney(p.currency, p.absorbed_value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>
    </div>
  )
}

// ------------------------------------------------------------------ SOW

function SowPanel({ sows, sowId, setSowId, sow, onCreated }: {
  sows: SowSummary[]; sowId: string; setSowId: (id: string) => void; sow: Sow | null; onCreated: (id: string) => void
}) {
  const [deals, setDeals] = useState<DealRow[]>([])
  const [dealId, setDealId] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    api.get<DealRow[]>('/api/deals').then((d) => setDeals(d.filter((x) => ['ready', 'approved'].includes(x.status)))).catch(() => setDeals([]))
  }, [])
  const fromDeal = async () => {
    setBusy(true)
    setErr(null)
    try {
      const s = await api.post<SowSummary>(`/api/scope/sows/from-deal/${dealId}`, {})
      onCreated(s.sow_id)
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }
  const rates = sow ? Object.values(sow.cr_rates) : []
  const blended = rates.length ? rates.reduce((a, b) => a + b, 0) / rates.length : 0
  return (
    <Section title="Signed scope (SOW)" right={sow ? <Pill tone={sow.source === 'deal' ? 'blue' : ''}>{sow.source === 'deal' ? 'from Deal Desk' : 'signed SOW'}</Pill> : null}>
      <div className="col">
        <select value={sowId} onChange={(e) => setSowId(e.target.value)}>
          {sows.map((s) => (
            <option key={s.sow_id} value={s.sow_id}>{s.client}: {s.project_name} ({s.sow_id})</option>
          ))}
        </select>
        {sow && (
          <>
            <dl className="kv">
              <dt>Contract</dt><dd>{sow.contract_type === 'fixed' ? 'Fixed price' : 'Time & materials'} · {fmtMoney(sow.currency, sow.contract_value)}</dd>
              <dt>Dates</dt><dd>{sow.start_date ?? '–'} to {sow.end_date ?? '–'} · warranty {sow.warranty_days ?? '–'} days</dd>
              <dt>CR rates</dt><dd>{sow.currency} {Math.min(...rates)}–{Math.max(...rates)}/h by role (avg {blended.toFixed(0)})</dd>
            </dl>
            <div className="col" style={{ gap: 12, maxHeight: 420, overflowY: 'auto' }}>
              {CLAUSE_GROUPS.map(([type, label]) => {
                const cs = sow.clauses.filter((c) => c.type === type)
                if (!cs.length) return null
                return (
                  <div key={type} className="col" style={{ gap: 6 }}>
                    <div className="tiny muted strong">{label.toUpperCase()}</div>
                    {cs.map((c) => (
                      <div key={c.id} className="row" style={{ alignItems: 'flex-start', flexWrap: 'nowrap' }}>
                        <span className="chip"><b>{c.id}</b></span>
                        <div><div className="small strong">{c.title}</div><div className="tiny muted">{c.text}</div></div>
                      </div>
                    ))}
                  </div>
                )
              })}
            </div>
          </>
        )}
        <div className="col" style={{ gap: 6, borderTop: '1px solid var(--border)', paddingTop: 10 }}>
          <div className="tiny muted strong">TURN A DEAL DESK PROPOSAL INTO AN SOW</div>
          <div className="row" style={{ flexWrap: 'nowrap' }}>
            <select value={dealId} onChange={(e) => setDealId(e.target.value)}>
              <option value="">Choose a finished deal…</option>
              {deals.map((d) => <option key={d.id} value={d.id}>{d.title}</option>)}
            </select>
            <button className="btn btn-sm" disabled={!dealId || busy} onClick={() => void fromDeal()}>Create SOW</button>
          </div>
          {err && <div className="notice red tiny">{err}</div>}
        </div>
      </div>
    </Section>
  )
}

// ------------------------------------------------------------------ message input

function MessagePanel({ sow, samples, onStarted }: { sow: Sow | null; samples: Sample[]; onStarted: (id: string) => void }) {
  const [subject, setSubject] = useState('')
  const [text, setText] = useState('')
  const [sampleId, setSampleId] = useState<string | null>(null)
  const [doc, setDoc] = useState<Attachment | null>(null)
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setSampleId(null)
    setDoc(null)
  }, [sow?.sow_id])

  const pick = (s: Sample) => {
    setSampleId(s.id)
    setDoc(null)
    setSubject(s.subject)
    setText(s.text)
  }
  const upload = async (f: File) => {
    setErr(null)
    setUploading(true)
    try {
      const a = await uploadDocument(f)
      setDoc(a)
      setSampleId(null)
      setSubject(a.name)
      setText(a.preview)
    } catch (e) {
      setErr((e as Error).message)
    }
    setUploading(false)
  }
  const run = async () => {
    if (!sow) return
    setBusy(true)
    setErr(null)
    try {
      const body = doc
        ? { sow_id: sow.sow_id, attachment_id: doc.id, subject }
        : sampleId && samples.find((s) => s.id === sampleId)?.text === text
          ? { sow_id: sow.sow_id, sample_id: sampleId }
          : { sow_id: sow.sow_id, message: text, subject }
      const r = await api.post<{ id: string }>('/api/scope/analyses', body)
      onStarted(r.id)
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }
  return (
    <Section
      title="Client message"
      right={
        <>
          <input ref={fileRef} type="file" accept={ACCEPT} hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) void upload(f); e.target.value = '' }} />
          <button className="btn btn-sm" disabled={uploading} onClick={() => fileRef.current?.click()}>{uploading ? 'Reading…' : <><Paperclip size={14} /> Upload PDF / TXT</>}</button>
        </>
      }
    >
      <div className="col">
        {samples.length > 0 && (
          <div className="col" style={{ gap: 6 }}>
            <div className="tiny muted strong">SAMPLE MESSAGES FOR THIS PROJECT</div>
            <div className="row">
              {samples.map((s) => (
                <button key={s.id} className="btn btn-chip" style={sampleId === s.id ? { borderColor: 'var(--accent)' } : undefined} onClick={() => pick(s)} title={`${s.channel} from ${s.from}`}>
                  {s.channel === 'ticket' ? <Ticket size={13} /> : <Mail size={13} />} {s.subject}
                </button>
              ))}
            </div>
          </div>
        )}
        {doc && (
          <div className="row">
            <span className="file-chip">📄 {doc.name} · {doc.pages}p · {fmtInt(doc.chars)} chars
              <button onClick={() => { setDoc(null); setText(''); setSubject('') }} aria-label="Remove">×</button>
            </span>
            {doc.injection_suspected && <Pill tone="amber"><TriangleAlert size={12} /> hidden instructions removed</Pill>}
          </div>
        )}
        <input placeholder="Subject (optional)" value={subject} onChange={(e) => setSubject(e.target.value)} />
        <textarea
          value={text}
          onChange={(e) => { setText(e.target.value); setDoc(null) }}
          placeholder={sow ? `Paste an email or ticket from ${sow.client}…` : 'Choose an SOW first'}
          style={{ minHeight: 200 }}
        />
        {err && <div className="notice red small">{err}</div>}
        <div className="row">
          <button className="btn btn-primary" disabled={!sow || busy || text.trim().length < 10} onClick={() => void run()}>
            {busy ? 'Starting…' : 'Check against SOW'}
          </button>
          <span className="tiny muted">About 10–25 seconds · the reply is a draft; nothing is sent.</span>
        </div>
      </div>
    </Section>
  )
}

// ------------------------------------------------------------------ one analysis

function AnalysisView({ id, onChanged }: { id: string; onChanged: () => void }) {
  const [clauseMap, setClauseMap] = useState<Record<string, { title: string; text: string }>>({})
  const [impact, setImpact] = useState<Impact>(null)
  const [history, setHistory] = useState<{ ts: string; actor: string; summary: string }[]>([])
  const sowId = (useAnalysisSow(id))
  useEffect(() => {
    if (!sowId) return
    api.get<any>(`/api/scope/sows/${sowId}`).then((sw) => setClauseMap(Object.fromEntries((sw.clauses ?? []).map((c: any) => [c.id, { title: c.title, text: c.text }])))).catch(() => {})
    const code = sowId.replace(/^SOW-/, '')
    api.get<any>(`/api/projects/health/${code}`).then((p) => setImpact({
      people: p.team.length, weekly_hours: p.team.reduce((t: number, m: any) => t + (m.allocation_pct / 100) * 40, 0),
      next_milestone: p.milestones.find((m: any) => m.status === 'upcoming' || m.status === 'at_risk') ?? null,
    })).catch(() => setImpact(null))
  }, [sowId])
  useEffect(() => { api.get<any>(`/api/activity/${id}`).then((d) => setHistory(d.audit ?? [])).catch(() => setHistory([])) }, [id])
  const [a, setA] = useState<Analysis | null>(null)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    let stop = false
    let timer: number | undefined
    const load = async () => {
      try {
        const d = await api.get<Analysis>(`/api/scope/analyses/${id}`)
        if (stop) return
        setA(d)
        setErr(null)
        if (d.status === 'queued' || d.status === 'running') timer = window.setTimeout(load, 1200)
        else onChanged()
      } catch (e) {
        if (!stop) setErr((e as Error).message)
      }
    }
    void load()
    return () => {
      stop = true
      if (timer) window.clearTimeout(timer)
    }
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <div className="notice red small">{err}</div>
  if (!a) return <div className="card card-pad muted small">Loading…</div>
  const r = a.results
  const items = r.items ?? []
  const crs = Object.fromEntries((r.pricing?.items ?? []).map((c) => [c.ask_id, c]))
  const running = a.status === 'queued' || a.status === 'running'
  const clauses = clauseMap
  const high = a.screen.findings.filter((f) => f.severity === 'high')

  return (
    <div className="card">
      <div className="card-head">
        <div>
          <h3>{a.title}</h3>
          <div className="tiny muted">{a.input.source} · {fmtDateTime(a.created_at)}{a.created_by ? ` · by ${a.created_by}` : ''}</div>
        </div>
        <div className="row">
          {a.status === 'blocked' ? <Pill tone="red">Blocked by safety filter</Pill> : <StatusPill status={a.status} />}
          {a.usage && <span className="chip">tokens <b>{fmtInt(a.usage.input_tokens + a.usage.output_tokens)}</b> · <b>{fmtUsd(a.usage.cost_usd, 5)}</b></span>}
        </div>
      </div>
      <div className="card-body col" style={{ gap: 14 }}>
        <div className="row">
          {Object.values(a.steps).map((s) => (
            <span key={s.key} title={`${s.job ?? ''}${s.summary ? `\n${s.summary}` : ''}`}>
              <Pill tone={STEP_TONE[s.status]} pulse={s.status === 'running' ? true : undefined}>
                {s.status === 'done' ? <Check size={13} /> : s.status === 'failed' ? <X size={13} /> : s.status === 'skipped' ? <Minus size={13} /> : null} {s.label}
              </Pill>
            </span>
          ))}
        </div>

        {a.error && <div className={`notice ${a.status === 'blocked' ? 'amber' : 'red'} small`}>{a.error}</div>}
        {high.length > 0 && (
          <div className="notice amber small">
            <TriangleAlert size={16} color="var(--amber)" />
            <div>
              <b>Instructions aimed at the AI were found in the client's message and removed before any agent read it.</b>
              {high.map((f, i) => <div key={i} className="tiny">• {f.message} {f.snippet && <span className="mono">“{f.snippet}”</span>}</div>)}
            </div>
          </div>
        )}
        {running && <div className="notice blue small">The agents are reading the message and the SOW…</div>}

        {items.length > 0 && (
          <table className="tbl">
            <thead>
              <tr><th style={{ width: '42%' }}>Client asked · signed scope says</th><th>Verdict</th><th>Why</th><th className="num">Change request</th></tr>
            </thead>
            <tbody>
              {items.map((it) => {
                const cr = crs[it.ask_id]
                return (
                  <tr key={it.ask_id}>
                    <td>
                      <div className="small strong">{it.ask_id}. {it.summary}</div>
                      <div className="side-by-side" style={{ marginTop: 6 }}>
                        <div className="quote-box client">“{it.quote}”</div>
                        <div className="col" style={{ gap: 4 }}>
                          {it.clause_ids.map((c) => (
                            <div key={c} className="quote-box sow"><b>{c}{clauses[c] ? ` · ${clauses[c].title}` : ''}</b>{clauses[c] ? <div>{clauses[c].text}</div> : null}</div>
                          ))}
                          {it.invalid_clause_ids.map((c) => <Pill key={c} tone="red">{c}? (not in the SOW)</Pill>)}
                          {!it.clause_ids.length && !it.invalid_clause_ids.length && <div className="tiny muted">no clause cited</div>}
                        </div>
                      </div>
                    </td>
                    <td>
                      <Pill tone={VERDICT[it.verdict][0]}>{VERDICT[it.verdict][1]}</Pill>
                      {it.downgraded && <div className="tiny muted" style={{ marginTop: 4 }}>Agent said “{it.model_verdict?.replace('_', ' ')}”; downgraded</div>}
                    </td>
                    <td className="small">
                      {it.reasoning}
                      {it.downgrade_reason && <div className="tiny red">{it.downgrade_reason}</div>}
                      {it.question_for_client && it.verdict === 'ambiguous' && <div className="tiny" style={{ marginTop: 4 }}>Q: {it.question_for_client}</div>}
                    </td>
                    <td className="num">
                      {cr ? (cr.estimated ? <><div className="strong">{fmtMoney(cr.currency, cr.price)}</div><div className="tiny muted">{cr.total_hours} h</div></> : <Pill tone="red">needs estimate</Pill>) : '–'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}

        {r.pricing && r.pricing.items.length > 0 && <CrSummary pricing={r.pricing} impact={impact} />}

        {r.reply_text && (
          <div className="col" style={{ gap: 6 }}>
            <div className="row">
              <div className="strong">Reply draft</div>
              <span className="spacer" />
              {(r.leak_findings ?? []).length ? <Pill tone="red">Leak guard redacted {(r.leak_findings ?? []).length} line(s)</Pill> : <Pill tone="green">Leak guard: clean</Pill>}
              <button className="btn btn-sm" onClick={() => void navigator.clipboard.writeText(r.reply_text ?? '')}>Copy</button>
            </div>
            <div className="card card-pad"><Markdown text={r.reply_text} variant="chat" /></div>
          </div>
        )}

        {(a.status === 'ready' || a.decision) && <DecisionBar a={a} onDone={(d) => { setA(d); onChanged(); api.get<any>(`/api/activity/${a.id}`).then((x) => setHistory(x.audit ?? [])).catch(() => {}) }} />}
        {history.length > 0 && (
          <div className="small muted"><b>Decision history (audit trail):</b> {history.map((h) => `${fmtDateTime(h.ts)} ${h.actor}: ${h.summary}`).join(' · ')}</div>
        )}
      </div>
    </div>
  )
}

type Impact = { people: number; weekly_hours: number; next_milestone: { name: string; planned: string } | null } | null

function CrSummary({ pricing, impact }: { pricing: Pricing; impact: Impact }) {
  const roles = useMemo(() => {
    const t: Record<string, number> = {}
    for (const c of pricing.items) for (const [r, h] of Object.entries(c.hours_by_role)) t[r] = (t[r] ?? 0) + h
    return Object.entries(t).sort((x, y) => y[1] - x[1])
  }, [pricing])
  return (
    <div className="grid g4">
      <Stat label="Change requests" value={pricing.items.length} foot={`${pricing.counts.in_scope ?? 0} in scope · ${pricing.counts.warranty_fix ?? 0} warranty · ${pricing.counts.ambiguous ?? 0} to clarify`} small />
      <Stat label="CR hours (incl. PM)" value={`${fmtInt(pricing.total_hours)} h`} foot={roles.map(([r, h]) => `${r} ${fmtInt(h)}`).join(' · ')} small />
      <Stat label="CR value" value={fmtMoney(pricing.currency, pricing.total_price)} foot={pricing.warnings.length ? pricing.warnings[0] : 'at the SOW’s change-request rates'} small />
      <Stat label="Schedule impact (estimate)" small
        value={impact && impact.weekly_hours ? `≈ +${(pricing.total_hours / (impact.weekly_hours * 0.85)).toFixed(1)} wks` : '–'}
        foot={impact ? `if the current team (${impact.people} people, ${Math.round(impact.weekly_hours)} h/week) absorbs it` + (impact.next_milestone ? `; next milestone ${impact.next_milestone.name} on ${impact.next_milestone.planned}` : '') : 'no delivery data for this project'} />
    </div>
  )
}

function DecisionBar({ a, onDone }: { a: Analysis; onDone: (d: Analysis) => void }) {
  const crs = a.results.pricing?.items ?? []
  const [absorb, setAbsorb] = useState<string[]>([])
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const decide = async (action: 'approve' | 'reject' | 'clarify') => {
    setBusy(true)
    setErr(null)
    try {
      await api.post(`/api/scope/analyses/${a.id}/decision`, { action, absorb_ask_ids: absorb, note })
      onDone(await api.get<Analysis>(`/api/scope/analyses/${a.id}`))
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }
  const d = a.decision
  if (d && d.action !== 'clarify')
    return (
      <div className="notice green small">
        <div>
          <b>{d.action === 'approve' ? 'Approved' : 'Rejected'}</b> by {d.approver} on {fmtDateTime(d.at)}
          {d.absorb_ask_ids.length > 0 && <> · absorbed as goodwill: {d.absorb_ask_ids.join(', ')}</>}
          {d.note && <> · “{d.note}”</>}
        </div>
      </div>
    )
  return (
    <div className="card card-pad col" style={{ gap: 8 }}>
      {d && d.action === 'clarify' && (
        <div className="notice amber small">Clarification requested by {d.approver} on {fmtDateTime(d.at)}: “{d.note}”. Decide again when the client answers.</div>
      )}
      <div className="row"><div className="strong">Your decision</div><span className="tiny muted">Approve logs the change requests in the scope ledger; ask for clarification if the request is ambiguous. Nothing is sent to the client. Every decision is audited.</span></div>
      {crs.length > 0 && (
        <div className="row small">
          <span className="muted">Absorb as goodwill (no charge):</span>
          {crs.map((c) => (
            <label key={c.ask_id} className="row" style={{ gap: 4 }}>
              <input type="checkbox" style={{ width: 'auto' }} checked={absorb.includes(c.ask_id)}
                onChange={(e) => setAbsorb((cur) => (e.target.checked ? [...cur, c.ask_id] : cur.filter((x) => x !== c.ask_id)))} />
              {c.ask_id} ({fmtMoney(c.currency, c.price)})
            </label>
          ))}
        </div>
      )}
      <div className="row" style={{ flexWrap: 'nowrap' }}>
        <input placeholder="Note (required to ask for clarification: the question for the client)" value={note} onChange={(e) => setNote(e.target.value)} />
        <button className="btn btn-primary" disabled={busy} onClick={() => void decide('approve')}>Approve</button>
        <button className="btn" disabled={busy} onClick={() => void decide('clarify')}>Request clarification</button>
        <button className="btn btn-danger" disabled={busy} onClick={() => void decide('reject')}>Reject</button>
      </div>
      {err && <div className="notice red small">{err}</div>}
      {a.screen.findings.length > 0 && (
        <div className="tiny muted">Safety screen: {a.screen.findings.map((f) => <Pill key={f.kind + f.snippet} tone={sevTone(f.severity)}>{f.kind}</Pill>)}</div>
      )}
    </div>
  )
}


// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyObj = any

function useAnalysisSow(id: string): string | null {
  const [sow, setSow] = useState<string | null>(null)
  useEffect(() => { api.get<AnyObj>(`/api/scope/analyses/${id}`).then((d) => setSow(d.sow?.sow_id ?? d.input?.sow_id ?? null)).catch(() => setSow(null)) }, [id])
  return sow
}
