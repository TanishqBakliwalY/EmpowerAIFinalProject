/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState } from 'react'
import { Swords } from 'lucide-react'
import { api } from '../api'
import { RunStatus } from '../cards'
import { StatusPill, fmtDateTime, fmtMoney, fmtUsd, go } from '../lib'

export default function DealRoomPage() {
  const [deals, setDeals] = useState<any[] | null>(null)
  const [runs, setRuns] = useState<any[]>([])
  useEffect(() => {
    api.get<any[]>('/api/deals').then((d) => setDeals(d.filter((x) => x.price != null))).catch(() => setDeals([]))
    api.get<any[]>('/api/activity?module=deal_room').then(setRuns).catch(() => setRuns([]))
  }, [])
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Sales</div>
          <h1>Deal Room</h1>
          <div className="sub">Rehearse a pricing call before the quote goes out. A client agent built from the client's own email (with a hidden budget
            ceiling) negotiates with Empower's negotiator agent; code prices every offer and enforces the discount and margin rules; a coach turns it into a
            plan for the real call. On each deal you can also test discounts, scope, model and timeline in the scenario editor.</div>
        </div>
      </div>
      <div className="card">
        <div className="card-head"><h3>Pick a deal to rehearse</h3><span className="tiny muted">Opens the deal's Deal Room tab</span></div>
        <table className="tbl">
          <thead><tr><th>Deal</th><th>Status</th><th className="right">Recommended price</th><th className="right">Margin</th><th /></tr></thead>
          <tbody>
            {!deals && <tr><td colSpan={5}><div className="empty"><span className="spinner" /></div></td></tr>}
            {deals?.map((d) => (
              <tr key={d.id} className="click" onClick={() => go(`/deals/${d.id}?tab=room`)}>
                <td><div className="strong">{d.title.split(' · ')[0]}</div><div className="tiny muted">{d.title.split(' · ').slice(1).join(' · ')}</div></td>
                <td><StatusPill status={d.status} /></td>
                <td className="right">{fmtMoney(d.currency, d.price)}<div className="tiny muted">{d.model === 'fixed' ? 'fixed' : 'T&M'}</div></td>
                <td className="right">{d.margin_pct != null ? `${d.margin_pct}%` : '–'}</td>
                <td className="right"><span className="btn btn-sm"><Swords size={14} /> Rehearse</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card">
        <div className="card-head"><h3>Rehearsals so far</h3></div>
        <table className="tbl">
          <thead><tr><th>Rehearsal</th><th>Status</th><th>Outcome / coach</th><th className="right">Cost</th></tr></thead>
          <tbody>
            {runs.length === 0 && <tr><td colSpan={4}><div className="empty">No rehearsals yet.</div></td></tr>}
            {runs.map((r) => (
              <tr key={r.id} className="click" onClick={() => go(`/activity/${r.id}`)}>
                <td><div className="strong small">{r.title}</div><div className="tiny muted">{r.trigger} · {fmtDateTime(r.created_at)}</div></td>
                <td><RunStatus s={r.status === 'awaiting_approval' ? 'completed' : r.status} /></td>
                <td className="small" style={{ maxWidth: 520 }}>{r.summary}</td>
                <td className="right small mono">{fmtUsd(r.cost_usd, 4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
