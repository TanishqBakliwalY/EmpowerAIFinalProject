import { useEffect, useRef, useState, type DragEvent } from 'react'
import { ChevronDown, FileText, LoaderCircle, Paperclip, Sparkles, TriangleAlert, X } from 'lucide-react'
import { api } from '../api'
import { useCopilot } from '../copilot'
import { ACCEPT, uploadDocument } from '../files'
import { fmtK, go } from '../lib'
import type { Attachment, Meta, Sample } from '../types'

const FLOW: { n: string; name: string; kind: 'code' | 'agent' | 'par'; text: string }[] = [
  { n: '0', name: 'Safety screen', kind: 'code', text: 'Strips hidden text, flags instructions aimed at the AI.' },
  { n: '1', name: 'Requirements Analyst', kind: 'agent', text: 'Spec, open questions, assumptions, client history.' },
  { n: '2', name: 'Solution Architect', kind: 'agent', text: 'Feasibility vs Empower skills, stack, work packages, risks.' },
  { n: '3', name: 'Estimator', kind: 'agent', text: 'Hours per role from what similar work actually took.' },
  { n: '4', name: 'Staffing Planner ‖ Pricing Strategist', kind: 'par', text: 'Real team from who is free; fixed vs T&M within policy. Run in parallel.' },
  { n: '5', name: 'Deal Critic', kind: 'agent', text: 'Red-team review; sends fixable problems back once.' },
  { n: '6', name: 'Proposal Writer', kind: 'agent', text: 'Client-facing prose. No tools, never sees costs.' },
  { n: '7', name: 'Leak guard', kind: 'code', text: 'Blocks costs, salaries, margins or prompt text in the proposal.' },
]

const PLACEHOLDER =
  "Paste the client's email or RFP here, or drop a PDF on this box…\n\n" +
  'e.g. "Hi Empower, we run 14 dental clinics and want a booking app with reminders and payments. ' +
  'We need HIPAA compliance and want to launch by April. Budget around $60-80k…"'

const COUNTRIES = ['US', 'UK', 'DE', 'BE', 'NL', 'FR', 'IE', 'AE', 'AU', 'NZ', 'ZA', 'JP', 'CA', 'SG']

export default function NewDeal({ meta }: { meta: Meta | null }) {
  const [samples, setSamples] = useState<Sample[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [brief, setBrief] = useState('')
  const [client, setClient] = useState('')
  const [country, setCountry] = useState('')
  const [currency, setCurrency] = useState<'USD' | 'EUR' | 'GBP'>('USD')
  const [start, setStart] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [doc, setDoc] = useState<Attachment | null>(null)
  const [uploading, setUploading] = useState(false)
  const [over, setOver] = useState(false)
  const [samplePdfs, setSamplePdfs] = useState<{ name: string; label: string }[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const { ask } = useCopilot()
  const max = meta?.limits.max_brief_chars ?? 40000

  useEffect(() => {
    api.get<Sample[]>('/api/deals/samples').then(setSamples).catch(() => setSamples([]))
    api.get<{ name: string; label: string }[]>('/api/files/samples/list').then(setSamplePdfs).catch(() => setSamplePdfs([]))
  }, [])

  // A document (uploaded or sample) is extracted and screened on the server; its clean text fills the box.
  const loadDoc = async (getDoc: () => Promise<Attachment>) => {
    setErr(null)
    setUploading(true)
    try {
      const a = await getDoc()
      const full = await api.get<Attachment>(`/api/files/${a.id}`)
      setDoc(a)
      setBrief(full.text ?? a.preview)
      setSel(null)
    } catch (e) {
      setErr((e as Error).message)
    }
    setUploading(false)
  }
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    const f = e.dataTransfer.files[0]
    if (f) void loadDoc(() => uploadDocument(f))
  }

  const pick = (s: Sample) => {
    setSel(s.id)
    setDoc(null)
    setBrief(s.brief)
    setClient(s.client_name)
    setCountry(s.client_country)
    setCurrency(s.currency as 'USD' | 'EUR' | 'GBP')
    setErr(null)
  }

  const run = async () => {
    setBusy(true)
    setErr(null)
    try {
      const r = await api.post<{ id: string }>('/api/deals', {
        brief,
        client_name: client,
        client_country: country,
        currency,
        desired_start: start,
      })
      go(`/deals/${r.id}`)
    } catch (e) {
      setErr((e as Error).message)
      setBusy(false)
    }
  }

  const tooLong = brief.length > max
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Deal Desk</h1>
          <div className="sub">
            Paste what the client sent (an email, RFP or call notes). Seven agents turn it into a feasibility view, an estimate
            grounded in Empower's own delivery history, a team built from people who are actually free, a price within policy,
            and a proposal draft for you to approve.
          </div>
        </div>
      </div>

      <div className="grid" style={{ gridTemplateColumns: 'minmax(0, 1.65fr) minmax(0, 1fr)' }}>
        <div className="card">
          <div className="card-head">
            <h3>Client request</h3>
            <div className="row">
              <span className={`tiny ${tooLong ? 'red' : 'muted'}`}>
                {brief.length.toLocaleString()} / {max.toLocaleString()} characters
              </span>
              <input
                ref={fileRef}
                type="file"
                accept={ACCEPT}
                hidden
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) void loadDoc(() => uploadDocument(f))
                  e.target.value = ''
                }}
              />
              <button className="btn btn-sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
                {uploading ? <LoaderCircle size={14} className="spin" /> : <Paperclip size={14} />} Upload PDF / TXT
              </button>
            </div>
          </div>
          <div className="card-body col" style={{ gap: 14 }}>
            {doc && (
              <div className="row">
                <span className={`file-chip ${doc.injection_suspected ? 'warn' : ''}`}>
                  {doc.injection_suspected ? <TriangleAlert size={13} /> : <FileText size={13} />} {doc.name} · {doc.pages} page{doc.pages === 1 ? '' : 's'} · {fmtK(doc.chars)} characters
                  <button onClick={() => { setDoc(null); setBrief('') }} aria-label="Remove"><X size={13} /></button>
                </span>
                <span className="tiny muted">Text extracted on Empower's server and safety-screened; edit it below if needed.</span>
              </div>
            )}
            {doc && doc.findings.length > 0 && (
              <div className={`notice ${doc.injection_suspected ? 'amber' : ''} small`}>
                <TriangleAlert size={16} color="var(--amber)" />
                <div>
                  <b>The safety screen changed this document before any agent sees it.</b>
                  {doc.findings.map((f, i) => (
                    <div key={i} className="tiny">
                      • {f.message} {f.snippet && <span className="mono">“{f.snippet.slice(0, 140)}”</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
            <div
              className={`dropzone ${over ? 'over' : ''}`}
              onDragOver={(e) => {
                e.preventDefault()
                setOver(true)
              }}
              onDragLeave={() => setOver(false)}
              onDrop={onDrop}
            >
              <textarea
                value={brief}
                onChange={(e) => {
                  setBrief(e.target.value)
                  setSel(null)
                }}
                placeholder={PLACEHOLDER}
                style={{ minHeight: 300 }}
              />
              {over && <div className="drop-hint">Drop the client's PDF or text file</div>}
            </div>
            <div className="grid g4">
              <label className="field">
                Client name
                <input value={client} onChange={(e) => setClient(e.target.value)} placeholder="optional" />
              </label>
              <label className="field">
                Country
                <input list="countries" value={country} onChange={(e) => setCountry(e.target.value.toUpperCase())} placeholder="US, DE, UK…" />
                <datalist id="countries">
                  {COUNTRIES.map((c) => (
                    <option key={c} value={c} />
                  ))}
                </datalist>
              </label>
              <label className="field">
                Quote currency
                <select value={currency} onChange={(e) => setCurrency(e.target.value as 'USD' | 'EUR' | 'GBP')}>
                  <option>USD</option>
                  <option>EUR</option>
                  <option>GBP</option>
                </select>
              </label>
              <label className="field">
                Earliest start
                <input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              </label>
            </div>
            {err && <div className="notice red small">{err}</div>}
            <div className="row">
              <button className="btn btn-primary btn-lg" disabled={busy || brief.trim().length < 40 || tooLong} onClick={run}>
                {busy ? <LoaderCircle size={17} className="spin" /> : <Sparkles size={17} />} Run Deal Desk
              </button>
              <span className="muted small">
                Takes about 2–3 minutes. Nothing is sent to the client: you review and approve every proposal.
              </span>
              <span className="spacer" />
              <button className="btn btn-ghost btn-sm" onClick={() => ask('I have a new client request. What do you need from me to quote it?', false)}>
                <Sparkles size={14} /> Prefer to chat? Ask Emi
              </button>
            </div>
          </div>
        </div>

        <div className="col" style={{ gap: 16 }}>
          <div className="card">
            <div className="card-head">
              <h3>Try a sample request</h3>
            </div>
            <div className="card-body col" style={{ gap: 8 }}>
              {samplePdfs.length > 0 && (
                <div className="col" style={{ gap: 6, marginBottom: 6 }}>
                  <div className="tiny muted strong">SAMPLE PDF FILES</div>
                  <div className="row">
                    {samplePdfs.map((pdf) => (
                      <button
                        key={pdf.name}
                        className="btn btn-chip"
                        title={pdf.label}
                        disabled={uploading}
                        onClick={() => void loadDoc(() => api.post<Attachment>(`/api/files/samples/${pdf.name}`, {}))}
                      >
                        <FileText size={13} /> {pdf.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="tiny muted strong">SAMPLE EMAILS</div>
              {samples.map((s) => (
                <div key={s.id} className={`sample-card ${sel === s.id ? 'sel' : ''}`} onClick={() => pick(s)}>
                  <span className="flag">{s.client_country}</span>
                  <div>
                    <div className="strong small">{s.label}</div>
                    <div className="muted tiny">
                      {s.client_name} · {s.currency}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <details className="card card-pad howto">
            <summary><ChevronDown size={16} /> What happens when you click Run</summary>
            <div className="flow">
              {FLOW.map((f) => (
                <div className="flow-item" key={f.n}>
                  <div className={`flow-num ${f.kind}`}>{f.n}</div>
                  <div>
                    <div className="strong small">
                      {f.name}{' '}
                      <span className={`pill ${f.kind === 'code' ? 'blue' : f.kind === 'par' ? 'violet' : 'green'}`} style={{ marginLeft: 4 }}>
                        {f.kind === 'code' ? 'code' : f.kind === 'par' ? '2 agents' : 'agent'}
                      </span>
                    </div>
                    <div className="muted tiny">{f.text}</div>
                  </div>
                </div>
              ))}
              <div className="notice tiny" style={{ marginTop: 6 }}>
                Agents choose; Empower's calculators count. Totals, dates, prices and margins are computed in code from the rate card
                and policy, so they can't be invented or talked down by a prompt.
              </div>
            </div>
          </details>
        </div>
      </div>
    </div>
  )
}
