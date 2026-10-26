import { useEffect, useState } from 'react'
import { Eye, EyeOff, Flame, Gavel, Handshake, LoaderCircle, Play, Scale, Smile, Sparkles, Swords } from 'lucide-react'
import { api } from '../api'
import { List, Pill, Section, fmtDate, fmtDateTime, fmtMoney, fmtUsd } from '../lib'
import type { Deal } from '../types'

type Offer = {
  model: string; scope: string; discount_pct: number; currency: string; price: number; go_live: string
  margin_pct: number; needs_director: boolean; below_floor: boolean; budget_gap_pct: number | null; notes: string[]
}
type Entry = {
  speaker: 'client' | 'empower'; round: number; text: string
  stance?: string; objections?: string[]; private?: string
  card?: string; offer?: Offer; concessions?: string[]; reasoning?: string; scrubbed?: number; leak_redacted?: boolean
}
type Coach = {
  outcome: string; headline: string; likely_objections: string[]; concession_path: string[]; walk_away_point: string
  what_worked: string[]; what_to_avoid: string[]; questions_to_ask: string[]
}
type Rehearsal = {
  id: string; status: string; error: string | null; created_at: string
  input: { deal_id: string; style: string; created_by: string }
  results: {
    transcript: Entry[]; coach: Coach | null; client_name: string; client_ceiling?: number
    outcome: { result: string; rounds: number; final_offer: Offer; opening_price: number; price_movement_pct: number } | null
  }
  usage?: { cost_usd: number; input_tokens: number; output_tokens: number }
}
type Summary = { id: string; status: string; style: string; created_at: string; created_by: string; result: string | null
  final_price: number | null; currency: string | null; cost_usd: number | null }

const STYLES = [
  { key: 'friendly', label: 'Friendly', icon: Smile, text: 'Keen to work with you; pushes back once or twice.' },
  { key: 'balanced', label: 'Balanced', icon: Scale, text: 'Comparing vendors; expects a real concession.' },
  { key: 'tough', label: 'Tough', icon: Flame, text: 'Procurement mindset; challenges every number, may walk.' },
]
const RESULT: Record<string, [string, string]> = {
  deal: ['green', 'Deal agreed'], no_deal: ['red', 'Client walked away'], no_agreement: ['amber', 'No agreement yet'],
}
const initials = (s: string) => s.split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join('').toUpperCase()

export default function DealRoom({ deal }: { deal: Deal }) {
  const [list, setList] = useState<Summary[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [style, setStyle] = useState('balanced')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const refresh = async (pick?: string) => {
    const l = await api.get<Summary[]>(`/api/deals/${deal.id}/rehearsals`)
    setList(l)
    setSel((cur) => pick ?? cur ?? l[0]?.id ?? null)
  }
  useEffect(() => { refresh().catch((e) => setErr((e as Error).message)) }, [deal.id])

  const start = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.post<{ id: string }>(`/api/deals/${deal.id}/rehearsals`, { style })
      await refresh(r.id)
    } catch (e) {
      setErr((e as Error).message)
    }
    setBusy(false)
  }

  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="card room-hero">
        <div className="room-hero-text">
          <div className="eyebrow"><Swords size={13} /> Deal Room</div>
          <h2>Rehearse the pricing call before you send the quote</h2>
          <p className="muted small" style={{ marginTop: 6, maxWidth: 640 }}>
            A simulated client, built from their own email with a hidden budget ceiling, negotiates with Empower's negotiator.
            Code prices every offer and enforces the discount and margin rules. A coach then shows what the client was really
            thinking and how to run the real call. Nothing is sent to the client.
          </p>
        </div>
        <div className="col" style={{ gap: 10, minWidth: 320 }}>
          <div className="style-pick">
            {STYLES.map((s) => (
              <button key={s.key} className={`style-opt ${style === s.key ? 'sel' : ''}`} onClick={() => setStyle(s.key)} title={s.text}>
                <s.icon size={18} />
                <span>{s.label}</span>
              </button>
            ))}
          </div>
          <div className="tiny muted">{STYLES.find((s) => s.key === style)?.text}</div>
          <button className="btn btn-primary btn-lg" disabled={busy} onClick={start}>
            {busy ? <LoaderCircle size={16} className="spin" /> : <Play size={16} />} Start rehearsal
          </button>
          <div className="tiny muted">About 1 minute · usually under $0.01</div>
        </div>
      </div>
      {err && <div className="notice red small">{err}</div>}

      {list.length > 1 && (
        <div className="row">
          <span className="small muted">Rehearsals:</span>
          {list.map((r) => (
            <button key={r.id} className={`btn btn-chip ${sel === r.id ? 'active-chip' : ''}`} onClick={() => setSel(r.id)}>
              {r.style} · {r.result ? RESULT[r.result]?.[1] ?? r.result : r.status} · {fmtDateTime(r.created_at)}
            </button>
          ))}
        </div>
      )}
      {sel ? <RehearsalView id={sel} onDone={() => refresh()} /> : (
        <div className="card empty">No rehearsal yet. Pick how tough the client should be and press Start.</div>
      )}
    </div>
  )
}

function RehearsalView({ id, onDone }: { id: string; onDone: () => void }) {
  const [r, setR] = useState<Rehearsal | null>(null)
  const [reveal, setReveal] = useState(false)
  useEffect(() => {
    let stop = false
    let timer: number | undefined
    const load = async () => {
      const d = await api.get<Rehearsal>(`/api/rehearsals/${id}`)
      if (stop) return
      setR(d)
      if (d.status === 'running') timer = window.setTimeout(load, 1500)
      else onDone()
    }
    setReveal(false)
    load()
    return () => {
      stop = true
      if (timer) window.clearTimeout(timer)
    }
  }, [id])
  if (!r) return <div className="card empty"><span className="spinner" /></div>

  const running = r.status === 'running'
  const res = r.results
  const offers = res.transcript.filter((e) => e.speaker === 'empower' && e.offer)
  const clientTurns = res.transcript.filter((e) => e.speaker === 'client')
  const name = res.client_name || 'Client'
  const out = res.outcome
  const done = !running && !!out

  return (
    <div className="col" style={{ gap: 16 }}>
      <div className="card card-pad">
        <div className="row">
          <div className="avatar room-client">{initials(name)}</div>
          <div>
            <div className="strong">{name} <span className="muted small">({r.input.style} client)</span></div>
            <div className="tiny muted">vs Empower Negotiator · referee: Empower's pricing calculator</div>
          </div>
          <span className="spacer" />
          {running && <Pill tone="blue" pulse>Round {Math.max(0, offers.length - 1)} in progress</Pill>}
          {out && <Pill tone={RESULT[out.result]?.[0]}>{out.result === 'deal' ? <Handshake size={13} /> : null}{RESULT[out.result]?.[1] ?? out.result}</Pill>}
          {r.status === 'failed' && <Pill tone="red">Failed</Pill>}
          {r.usage && <span className="tiny muted">{fmtUsd(r.usage.cost_usd, 4)}</span>}
        </div>
        <Temperature turns={clientTurns} running={running} />
        <OfferTrack offers={offers.map((e) => e.offer!)} ceiling={done ? res.client_ceiling : undefined} />
      </div>
      {r.error && <div className="notice red small">{r.error}</div>}

      <div className="card card-pad">
        <div className="row" style={{ marginBottom: 12 }}>
          <h3>The conversation</h3>
          <span className="spacer" />
          <button className="btn btn-sm" disabled={!done} onClick={() => setReveal((v) => !v)}
            title={done ? '' : 'Unlocks when the rehearsal ends'}>
            {reveal ? <EyeOff size={14} /> : <Eye size={14} />} {reveal ? 'Hide' : 'Reveal'} the client's private thoughts
          </button>
        </div>
        <div className="room-chat">
          {res.transcript.map((e, i) =>
            e.speaker === 'client' ? (
              <div key={i} className="room-msg client">
                <div className="avatar room-client sm">{initials(name)}</div>
                <div className="room-bubble">
                  <div className="room-who">{name} {e.stance && e.stance !== 'negotiating' && <Pill tone={e.stance === 'accept' ? 'green' : 'red'}>{e.stance === 'accept' ? 'accepts' : 'walks away'}</Pill>}</div>
                  <div>{e.text}</div>
                  {e.objections && e.objections.length > 0 && (
                    <div className="row" style={{ marginTop: 8, gap: 6 }}>{e.objections.map((o, j) => <Pill key={j} tone="amber">{o}</Pill>)}</div>
                  )}
                  {reveal && e.private && <div className="room-private"><Eye size={13} /> {e.private}</div>}
                </div>
              </div>
            ) : (
              <div key={i} className="room-msg empower">
                <div className="room-bubble">
                  <div className="room-who">Empower Negotiator{e.round === 0 ? ' · opening proposal' : ` · round ${e.round}`}</div>
                  <div>{e.text}</div>
                  {e.offer && <OfferTicket o={e.offer} />}
                  {e.concessions && e.concessions.length > 0 && (
                    <div className="row" style={{ marginTop: 8, gap: 6 }}>{e.concessions.map((c, j) => <Pill key={j} tone="violet">{c}</Pill>)}</div>
                  )}
                  {(e.scrubbed ?? 0) > 0 && <div className="tiny muted" style={{ marginTop: 6 }}><Gavel size={12} /> Referee removed {e.scrubbed} number(s) the negotiator typed itself.</div>}
                  {reveal && e.reasoning && <div className="room-private"><Sparkles size={13} /> {e.reasoning}</div>}
                </div>
                <div className="avatar room-empower sm">E</div>
              </div>
            ),
          )}
          {running && <div className="room-typing"><span /><span /><span /></div>}
        </div>
      </div>

      {res.coach && <CoachCard c={res.coach} ceiling={res.client_ceiling} currency={out?.final_offer.currency ?? ''} />}
    </div>
  )
}

function OfferTicket({ o }: { o: Offer }) {
  return (
    <div className="offer-ticket">
      <div>
        <div className="offer-price">{fmtMoney(o.currency, o.price)}</div>
        <div className="tiny muted">
          {o.model === 'fixed' ? 'fixed price' : 'time & materials'} · {o.scope === 'full' ? 'full scope' : o.scope === 'phase1' ? 'Phase 1' : 'paid discovery'}
          {o.discount_pct ? ` · ${o.discount_pct}% off` : ''} · {o.scope === 'discovery' ? 'results' : 'go-live'} {fmtDate(o.go_live)}
        </div>
      </div>
      <div className="col" style={{ gap: 4, alignItems: 'flex-end' }}>
        <Pill tone={o.needs_director ? 'amber' : 'green'}><Gavel size={12} /> {o.needs_director ? 'needs a Director' : 'within policy'}</Pill>
        <span className="tiny muted">margin {o.margin_pct}% (internal)</span>
      </div>
    </div>
  )
}

function Temperature({ turns, running }: { turns: Entry[]; running: boolean }) {
  // How warm the client is, turn by turn: objections cool it down, acceptance makes it hot.
  const heat = (e: Entry) => (e.stance === 'accept' ? 100 : e.stance === 'walk_away' ? 5 : Math.max(20, 70 - 12 * (e.objections?.length ?? 0)))
  return (
    <div className="room-temp">
      <span className="tiny muted">Client temperature</span>
      <div className="row" style={{ gap: 6 }}>
        {turns.map((e, i) => {
          const h = heat(e)
          return <span key={i} className="temp-chip" style={{ background: `hsl(${(h * 1.2).toFixed(0)}, 72%, 52%)` }} title={`Round ${e.round}: ${e.stance}`}>{e.round}</span>
        })}
        {running && <span className="temp-chip pending">…</span>}
      </div>
    </div>
  )
}

function OfferTrack({ offers: all, ceiling }: { offers: Offer[]; ceiling?: number }) {
  // Build offers share one price scale; a paid discovery is a different kind of price, so it is listed beside the track.
  const offers = all.map((o, i) => ({ ...o, round: i })).filter((o) => o.scope !== 'discovery')
  const disc = all.map((o, i) => ({ ...o, round: i })).filter((o) => o.scope === 'discovery')
  if (offers.length === 0) return null
  const prices = offers.map((o) => o.price)
  const lo = Math.min(...prices, ceiling ?? Infinity) * 0.92
  const hi = Math.max(...prices, ceiling ?? 0) * 1.04
  const pos = (v: number) => `${(100 * (v - lo)) / (hi - lo)}%`
  const cur = offers[0].currency
  return (
    <div className="offer-track">
      <div className="track-line" />
      {[...new Set(prices)].map((price) => {
        // Rounds that offered the same price share one dot: "2 & 4".
        const rounds = offers.filter((o) => o.price === price).map((o) => (o.round === 0 ? 'Open' : String(o.round)))
        const last = all[all.length - 1].scope !== 'discovery' && offers[offers.length - 1].price === price
        return (
          <div key={price} className={`track-dot ${last ? 'last' : ''}`} style={{ left: pos(price) }} title={fmtMoney(cur, price)}>
            <span>{rounds.join(' & ')}</span>
          </div>
        )
      })}
      {ceiling && (
        <div className={`track-ceiling ${(ceiling - lo) / (hi - lo) > 0.6 ? 'flip' : ''}`} style={{ left: pos(ceiling) }}>
          <span>client's hidden ceiling {fmtMoney(cur, ceiling)}</span>
        </div>
      )}
      <div className="track-labels tiny muted"><span>{fmtMoney(cur, lo)}</span><span>{fmtMoney(cur, hi)}</span></div>
      {disc.length > 0 && (
        <div className="track-note tiny">
          Paid discovery offered: {disc.map((o) => `round ${o.round} ${fmtMoney(o.currency, o.price)} (${o.model === 'fixed' ? 'fixed' : 'T&M'})`).join(' → ')}
        </div>
      )}
    </div>
  )
}

function CoachCard({ c, ceiling, currency }: { c: Coach; ceiling?: number; currency: string }) {
  return (
    <Section title={<span className="row" style={{ gap: 8 }}><Sparkles size={16} color="var(--violet)" /> Coach's plan for the real call</span>}
      right={ceiling ? <Pill tone="violet">client's ceiling was {fmtMoney(currency, ceiling)}</Pill> : null}>
      <p className="strong" style={{ marginBottom: 14 }}>{c.headline}</p>
      <div className="grid g2">
        <div><div className="tiny muted strong">LIKELY OBJECTIONS</div><List items={c.likely_objections} /></div>
        <div><div className="tiny muted strong">CONCESSION PATH</div>
          <ol style={{ margin: 0, paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 4 }}>{c.concession_path.map((x, i) => <li key={i}>{x}</li>)}</ol>
        </div>
        <div><div className="tiny muted strong">WHAT WORKED</div><List items={c.what_worked} /></div>
        <div><div className="tiny muted strong">WHAT TO AVOID</div><List items={c.what_to_avoid} /></div>
      </div>
      <div className="notice amber small" style={{ marginTop: 14 }}><b>Walk-away point:</b> {c.walk_away_point}</div>
      {c.questions_to_ask.length > 0 && (
        <div style={{ marginTop: 12 }}><div className="tiny muted strong">QUESTIONS THAT COULD UNLOCK IT</div><List items={c.questions_to_ask} /></div>
      )}
    </Section>
  )
}
