import { useEffect, useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { api } from '../api'
import { CopilotChat, useCopilot } from '../copilot'
import { fmtDateTime } from '../lib'
import type { ChatSummary } from '../types'

export default function CopilotPage() {
  const { chatId, setChatId, version, setOpen } = useCopilot()
  const [chats, setChats] = useState<ChatSummary[]>([])

  useEffect(() => setOpen(false), [setOpen])
  useEffect(() => {
    api.get<ChatSummary[]>('/api/copilot/chats').then(setChats).catch(() => setChats([]))
  }, [version, chatId])

  const remove = async (id: string) => {
    if (!window.confirm('Delete this chat?')) return
    await api.del(`/api/copilot/chats/${id}`)
    if (id === chatId) setChatId(null)
    setChats((c) => c.filter((x) => x.id !== id))
  }

  return (
    <div className="page" style={{ paddingBottom: 24 }}>
      <div className="page-head">
        <div>
          <div className="eyebrow">Assistant · Empower Copilot</div>
          <h1>Emi</h1>
          <div className="sub">
            Emi knows your deals, people and pricing policy. Ask a question, drop in a client RFP to get a quote, or have a client email drafted. Every number comes from a tool.
          </div>
        </div>
      </div>
      <div className="chat-layout">
        <div className="card chat-list">
          <div className="card-head">
            <h3>Chats</h3>
            <button className="btn btn-sm btn-primary" onClick={() => setChatId(null)}><Plus size={14} /> New</button>
          </div>
          <div className="items">
            {chats.length === 0 && <div className="muted small" style={{ padding: 10 }}>No chats yet.</div>}
            {chats.map((c) => (
              <div key={c.id} className={`chat-item ${c.id === chatId ? 'active' : ''}`} onClick={() => setChatId(c.id)} title={fmtDateTime(c.updated_at)}>
                <span className="t">{c.title}</span>
                <button className="del" title="Delete" onClick={(e) => { e.stopPropagation(); void remove(c.id) }}><Trash2 size={13} /></button>
              </div>
            ))}
          </div>
        </div>
        <div className="card" style={{ display: 'flex', overflow: 'hidden' }}>
          <CopilotChat />
        </div>
      </div>
    </div>
  )
}
