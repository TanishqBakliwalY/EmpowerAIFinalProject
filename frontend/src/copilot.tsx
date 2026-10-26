import { createContext, useCallback, useContext, useEffect, useRef, useState, type DragEvent, type ReactNode } from 'react'
import { ExternalLink, FileText, LoaderCircle, Maximize2, Paperclip, Plus, Send, Sparkles, TriangleAlert, X } from 'lucide-react'
import { api } from './api'
import { ACCEPT, uploadDocument } from './files'
import { fmtK, fmtUsd, go } from './lib'
import { Markdown } from './markdown'
import type { Attachment, ChatMessage } from './types'

// ------------------------------------------------------------------ shared state (like HW4's chat UI context)

type Pending = { text: string; send: boolean; id: number }
type CopilotState = {
  open: boolean
  setOpen: (o: boolean) => void
  chatId: string | null
  setChatId: (id: string | null) => void
  pending: Pending | null
  /** Open the panel and send (or pre-fill) a message. */
  ask: (text: string, send?: boolean) => void
  consume: () => void
  version: number
  bump: () => void
}

const Ctx = createContext<CopilotState | null>(null)
const KEY = 'empower_copilot_chat'

export function CopilotProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [chatId, setChatIdState] = useState<string | null>(() => localStorage.getItem(KEY))
  const [pending, setPending] = useState<Pending | null>(null)
  const [version, setVersion] = useState(0)
  const setChatId = useCallback((id: string | null) => {
    setChatIdState(id)
    if (id) localStorage.setItem(KEY, id)
    else localStorage.removeItem(KEY)
  }, [])
  const ask = useCallback((text: string, send = true) => {
    setOpen(true)
    setPending({ text, send, id: Date.now() })
  }, [])
  const consume = useCallback(() => setPending(null), [])
  const bump = useCallback(() => setVersion((v) => v + 1), [])
  return (
    <Ctx.Provider value={{ open, setOpen, chatId, setChatId, pending, ask, consume, version, bump }}>{children}</Ctx.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCopilot(): CopilotState {
  const c = useContext(Ctx)
  if (!c) throw new Error('useCopilot must be used inside <CopilotProvider>')
  return c
}

// ------------------------------------------------------------------ the chat

const GENERAL_STARTERS = [
  'Which deals are over the client’s budget?',
  'Who can start a React Native project next month?',
  'What is our margin floor and maximum discount?',
  'Draft a clarifying-questions email for the latest deal',
]
const DEAL_STARTERS = [
  'Summarise this deal for my director',
  'Why is the estimate this size?',
  'What if we give a 5% discount on fixed price?',
  'Draft an email sending the proposal',
]

export function CopilotChat({ pageDealId, compact }: { pageDealId?: string | null; compact?: boolean }) {
  const { chatId, setChatId, pending, consume, bump } = useCopilot()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [input, setInput] = useState('')
  const [files, setFiles] = useState<Attachment[]>([])
  const [uploading, setUploading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [over, setOver] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setErr(null)
    if (!chatId) {
      setMessages([])
      return
    }
    let stop = false
    setLoading(true)
    api
      .get<{ messages: ChatMessage[] }>(`/api/copilot/chats/${chatId}`)
      .then((r) => !stop && setMessages(r.messages))
      .catch(() => !stop && (setChatId(null), setMessages([])))
      .finally(() => !stop && setLoading(false))
    return () => {
      stop = true
    }
  }, [chatId, setChatId])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, sending])

  const addFiles = async (list: FileList | File[]) => {
    setErr(null)
    setUploading(true)
    try {
      for (const f of Array.from(list).slice(0, 3)) {
        const a = await uploadDocument(f)
        setFiles((cur) => [...cur.filter((x) => x.id !== a.id), a].slice(-3))
      }
    } catch (e) {
      setErr((e as Error).message)
    }
    setUploading(false)
  }

  const send = async (raw: string) => {
    let text = raw.trim()
    if (!text && files.length) text = 'Summarise the attached client request: what they want, budget, deadline and what is unclear.'
    if (!text || sending) return
    setErr(null)
    setSending(true)
    let id = chatId
    try {
      if (!id) {
        id = (await api.post<{ id: string }>('/api/copilot/chats', {})).id
        setChatId(id)
      }
      const att = files.map((f) => ({ id: f.id, name: f.name, pages: f.pages, chars: f.chars, injection_suspected: f.injection_suspected }))
      setMessages((m) => [...m, { id: -Date.now(), role: 'user', content: text, meta: att.length ? { attachments: att } : null }])
      setInput('')
      setFiles([])
      const reply = await api.post<ChatMessage>(`/api/copilot/chats/${id}/messages`, {
        content: text,
        attachment_ids: att.map((a) => a.id),
        page_deal_id: pageDealId ?? null,
      })
      setMessages((m) => [...m, reply])
      bump()
    } catch (e) {
      setErr((e as Error).message)
    }
    setSending(false)
    requestAnimationFrame(() => inputRef.current?.focus())
  }

  useEffect(() => {
    if (!pending || loading || sending) return
    consume()
    if (pending.send) void send(pending.text)
    else {
      setInput(pending.text)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [pending, loading, sending]) // eslint-disable-line react-hooks/exhaustive-deps

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    if (e.dataTransfer.files.length) void addFiles(e.dataTransfer.files)
  }

  const starters = pageDealId ? DEAL_STARTERS : GENERAL_STARTERS
  return (
    <div
      className="chat-main"
      onDragOver={(e) => {
        e.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <div className="chat-scroll" ref={scrollRef}>
        {loading && <div className="empty"><span className="spinner" /></div>}
        {!loading && messages.length === 0 && (
          <div className="chat-welcome">
            <div className="avatar bot" style={{ width: 46, height: 46 }}><Sparkles size={22} /></div>
            <h2>Hi, I'm Emi</h2>
            <div className="tiny muted" style={{ marginTop: -6 }}>Empower's ops copilot</div>
            <p className="muted small">
              {pageDealId
                ? 'Ask about this deal: the estimate, the team, what-if prices, or a client email.'
                : 'Ask about deals, staffing and pricing, or drop in a client RFP (PDF) and ask me to quote it.'}
            </p>
            <div className="starters">
              {starters.map((s) => (
                <button key={s} className="btn btn-chip" onClick={() => void send(s)} disabled={sending}>{s}</button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <Message key={m.id} m={m} compact={compact} onFollowup={(t) => void send(t)} disabled={sending} />
        ))}
        {sending && (
          <div className="msg assistant">
            <div className="avatar bot"><Sparkles size={15} /></div>
            <div className="bubble">
              <span className="typing"><i /><i /><i /></span>
              <span className="muted small" style={{ marginLeft: 8 }}>Checking Empower’s data…</span>
            </div>
          </div>
        )}
      </div>
      <div className={`chat-input ${over ? 'over' : ''}`}>
        {err && <div className="notice red small">{err}</div>}
        {(files.length > 0 || uploading) && (
          <div className="row">
            {files.map((f) => (
              <span key={f.id} className={`file-chip ${f.injection_suspected ? 'warn' : ''}`} title={f.findings.map((x) => x.message).join('\n')}>
                {f.injection_suspected ? <TriangleAlert size={13} /> : <FileText size={13} />} {f.name} · {f.pages}p · {fmtK(f.chars)} chars
                <button onClick={() => setFiles((cur) => cur.filter((x) => x.id !== f.id))} aria-label="Remove">×</button>
              </span>
            ))}
            {uploading && <span className="small muted row"><LoaderCircle size={14} className="spin" /> Reading file…</span>}
          </div>
        )}
        <div className="row" style={{ flexWrap: 'nowrap', alignItems: 'flex-end' }}>
          <input ref={fileRef} type="file" accept={ACCEPT} multiple hidden onChange={(e) => e.target.files && void addFiles(e.target.files)} />
          <button className="btn btn-ghost" title="Attach a PDF or text file" onClick={() => fileRef.current?.click()} disabled={sending || uploading}><Paperclip size={17} /></button>
          <textarea
            ref={inputRef}
            rows={2}
            value={input}
            placeholder={files.length ? 'Ask about the attached file, or say “quote this”…' : 'Ask Emi… (Enter to send, Shift+Enter for a new line)'}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void send(input)
              }
            }}
          />
          <button className="btn btn-primary" onClick={() => void send(input)} disabled={sending || (!input.trim() && !files.length)}>
            {sending ? <LoaderCircle size={16} className="spin" /> : <Send size={15} />}
          </button>
        </div>
        <div className="tiny muted">
          Uses Empower’s deals, staffing and pricing tools · documents are screened for hidden instructions · starting a deal takes ~2–3 min
        </div>
      </div>
    </div>
  )
}

function Message({ m, compact, onFollowup, disabled }: { m: ChatMessage; compact?: boolean; onFollowup: (t: string) => void; disabled: boolean }) {
  const meta = m.meta
  if (m.role === 'user')
    return (
      <div className="msg user">
        {!compact && <div className="avatar me">You</div>}
        <div className="bubble">
          <Markdown text={m.content} variant="chat" />
          {meta?.attachments?.length ? (
            <div className="row" style={{ marginTop: 6 }}>
              {meta.attachments.map((a) => (
                <span key={a.id} className="file-chip" style={{ background: 'rgba(255,255,255,.18)', color: '#fff', borderColor: 'rgba(255,255,255,.35)' }}>
                  {a.injection_suspected ? <TriangleAlert size={12} /> : <FileText size={12} />} {a.name}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    )
  const u = meta?.usage
  return (
    <div className="msg assistant">
      <div className="avatar bot"><Sparkles size={15} /></div>
      <div className="bubble">
        <Markdown text={m.content} variant="chat" />
        {meta?.started_deals?.map((d) => (
          <div key={d} style={{ marginTop: 8 }}>
            <button className="btn btn-sm btn-primary" onClick={() => go(`/deals/${d}`)}>Open deal {d} <ExternalLink size={13} /></button>
          </div>
        ))}
        {meta?.flagged?.length ? (
          <div className="notice amber tiny" style={{ marginTop: 8 }}><TriangleAlert size={13} /> Your message contained text that tries to instruct an AI; it was treated as data.</div>
        ) : null}
        {(meta?.tools?.length || u) && (
          <div className="msg-meta">
            {meta?.tools?.map((t, i) => <span key={i} className="tool-chip" title={JSON.stringify(t.args)}>{t.name}</span>)}
            {u && (
              <span title={`${u.input_tokens} input (${u.cached_tokens} cached) · ${u.output_tokens} output · ${u.requests} model calls`}>
                {fmtK(u.input_tokens + u.output_tokens)} tokens · {fmtUsd(u.cost_usd, 5)} · {meta?.seconds}s
              </span>
            )}
          </div>
        )}
        {meta?.followups?.length ? (
          <div className="followups">
            {meta.followups.map((f) => (
              <button key={f} className="btn btn-chip" disabled={disabled} onClick={() => onFollowup(f)}>{f}</button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

// ------------------------------------------------------------------ floating launcher + slide-over panel

export function CopilotDock({ pageDealId }: { pageDealId: string | null }) {
  const { open, setOpen, setChatId } = useCopilot()
  if (!open)
    return (
      <button className="fab no-print" onClick={() => setOpen(true)}>
        <span className="avatar bot" style={{ width: 26, height: 26 }}><Sparkles size={14} /></span>
        Ask Emi
      </button>
    )
  return (
    <>
      <div className="drawer-backdrop" onClick={() => setOpen(false)} />
      <aside className="drawer" role="dialog" aria-label="Emi, Empower's ops copilot">
        <div className="drawer-head">
          <div className="avatar bot"><Sparkles size={15} /></div>
          <div style={{ flex: 1 }}>
            <h3>Emi <span className="tiny muted" style={{ fontWeight: 400 }}>· ops copilot</span></h3>
            <div className="tiny muted">{pageDealId ? `Looking at deal ${pageDealId}` : 'Deals · staffing · pricing · client emails'}</div>
          </div>
          <button className="btn btn-ghost btn-sm" title="New chat" onClick={() => setChatId(null)}><Plus size={15} /> New</button>
          <button className="btn btn-ghost btn-sm" title="Open full page" onClick={() => { setOpen(false); go('/copilot') }}><Maximize2 size={15} /></button>
          <button className="btn btn-ghost btn-sm" title="Close" onClick={() => setOpen(false)}><X size={16} /></button>
        </div>
        <CopilotChat pageDealId={pageDealId} compact />
      </aside>
    </>
  )
}
