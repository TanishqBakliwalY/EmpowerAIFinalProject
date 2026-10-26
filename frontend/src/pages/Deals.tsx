import { useEffect, useState } from 'react'
import { api } from '../api'
import { Pill, StatusPill, fmtDateTime, fmtInt, fmtMoney, fmtUsd, go, useHashParams } from '../lib'
import type { DealRow } from '../types'

export default function Deals() {
  const [rows, setRows] = useState<DealRow[] | null>(null)
  const params = useHashParams()
  const only = params.status
  useEffect(() => {
    let t: number | undefined
    const load = () =>
      api.get<DealRow[]>('/api/deals').then((r) => {
        setRows(r)
        if (r.some((d) => d.status === 'running' || d.status === 'queued')) t = window.setTimeout(load, 2500)
      })
    load()
    return () => window.clearTimeout(t)
  }, [])

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Deals</h1>
          <div className="sub">Every client request run through the Deal Desk, with the recommended price, the critic's verdict and your decision.</div>
        </div>
        <a className="btn btn-primary" href="#/new">New deal</a>
      </div>
      {only && (
        <div className="notice blue small">Showing deals that need a decision only. <a href="#/deals">Show all deals</a></div>
      )}
      <div className="card">
        {rows === null ? (
          <div className="empty"><span className="spinner" /></div>
        ) : rows.length === 0 ? (
          <div className="empty">No deals yet. <a href="#/new">Run your first one</a>.</div>
        ) : (
          <table className="tbl">
            <thead>
              <tr>
                <th>Deal</th><th>By</th><th>Status</th><th className="num">Effort</th><th className="num">Recommended price</th>
                <th className="num">Margin</th><th>Critic</th><th>Flags</th><th className="num">AI cost</th><th>Started</th>
              </tr>
            </thead>
            <tbody>
              {rows.filter((d) => !only || d.status === only).map((d) => (
                <tr key={d.id} className="click" onClick={() => go(`/deals/${d.id}`)}>
                  <td style={{ maxWidth: 320 }}>
                    <div className="strong">{d.title.split(' · ')[0]}</div>
                    <div className="tiny muted">
                      {d.title.split(' · ').slice(1).join(' · ') || d.client_name}
                      {d.demo && <span className="pill blue" style={{ marginLeft: 6 }}>example</span>}
                    </div>
                  </td>
                  <td className="small nowrap">{d.created_by || '–'}{d.via === 'copilot' && <div className="tiny muted">via Emi</div>}</td>
                  <td><StatusPill status={d.status} /></td>
                  <td className="num">{d.hours ? `${fmtInt(d.hours)} h` : '–'}</td>
                  <td className="num">{d.price ? <>{fmtMoney(d.currency, d.price)} <span className="muted tiny">{d.model === 'tm' ? 'T&M' : 'fixed'}</span></> : '–'}</td>
                  <td className="num">{d.margin_pct != null ? `${d.margin_pct.toFixed(1)}%` : '–'}</td>
                  <td>{d.verdict ? <Pill tone={d.verdict === 'approve' ? 'green' : d.verdict === 'revise' ? 'violet' : 'amber'}>{d.verdict}</Pill> : '–'}</td>
                  <td>{d.flags > 0 ? <Pill tone="amber">⚠ {d.flags}</Pill> : <span className="muted">–</span>}</td>
                  <td className="num">{fmtUsd(d.cost_usd)}</td>
                  <td className="small muted nowrap">{fmtDateTime(d.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
