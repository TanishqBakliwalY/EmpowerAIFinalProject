import { useEffect, useState, type FormEvent } from 'react'
import { ArrowRight, BadgeCheck, LoaderCircle, Lock, ShieldCheck, Sparkles, Users } from 'lucide-react'
import { api } from '../api'
import { useAuth } from '../auth'
import { BrandMark } from '../brand'

type Demo = { email: string; password: string; name: string; role: string; role_label: string }

const ROLE_BLURB: Record<string, string> = {
  director: 'Everything, incl. approvals outside pricing policy and salary data',
  sales: 'Deal Desk, Deal Room, Emi, Scope Guard, Staffing',
  hr: 'Appraisals & hikes, Bench, Staffing',
}

export default function Login() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [demos, setDemos] = useState<Demo[]>([])

  useEffect(() => {
    api.get<Demo[]>('/api/auth/demo-accounts').then(setDemos).catch(() => setDemos([]))
  }, [])

  const go = async (e: string, p: string, key: string) => {
    setBusy(key)
    setErr(null)
    try {
      await signIn(e, p)
    } catch (x) {
      setErr((x as Error).message)
      setBusy(null)
    }
  }
  const submit = (ev: FormEvent) => {
    ev.preventDefault()
    void go(email, password, 'form')
  }

  return (
    <div className="login">
      <section className="login-hero">
        <div className="row" style={{ gap: 12 }}>
          <BrandMark size={44} tone="dark" />
          <div>
            <div className="brand-name" style={{ fontSize: 18 }}>Empower Ops Agents</div>
            <div className="brand-sub">for Empower Solutions</div>
          </div>
        </div>
        <div className="login-pitch">
          <h1>From a client's email to a priced, staffed proposal in minutes.</h1>
          <p>
            AI agents that work from Empower's own delivery history, real availability and pricing policy, with a person
            approving every decision.
          </p>
          <ul>
            <li><Sparkles size={16} /> Deal Desk and Emi: estimate, team, price and proposal</li>
            <li><ShieldCheck size={16} /> Scope-Creep Guard: every client ask checked against the SOW</li>
            <li><Users size={16} /> Bench, Staffing and Appraisals for the people side</li>
          </ul>
        </div>
        <div className="tiny" style={{ color: '#9fb6e6' }}>Demo build with synthetic company data · gpt-6-luna via Portkey</div>
      </section>

      <section className="login-panel">
        <form className="login-card" onSubmit={submit}>
          <div>
            <h2>Sign in</h2>
            <p className="muted small">Use your Empower account.</p>
          </div>
          <label className="field">
            Work email
            <input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@empower.demo" required />
          </label>
          <label className="field">
            Password
            <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
          {err && <div className="notice red small">{err}</div>}
          <button className="btn btn-primary btn-lg" type="submit" disabled={!!busy}>
            {busy === 'form' ? <LoaderCircle size={18} className="spin" /> : <Lock size={16} />} Sign in
          </button>

          {demos.length > 0 && (
            <div className="col" style={{ gap: 8, marginTop: 6 }}>
              <div className="divider" />
              <div className="tiny muted strong" style={{ letterSpacing: '.06em' }}>DEMO ACCOUNTS · ONE CLICK</div>
              {demos.map((d) => (
                <button key={d.email} type="button" className="demo-account" disabled={!!busy} onClick={() => void go(d.email, d.password, d.email)}>
                  <span className="avatar me">{d.name.split(' ').map((x) => x[0]).join('')}</span>
                  <span style={{ flex: 1, textAlign: 'left' }}>
                    <span className="strong">{d.name}</span> <span className="pill blue">{d.role_label}</span>
                    <span className="tiny muted" style={{ display: 'block' }}>{ROLE_BLURB[d.role]}</span>
                  </span>
                  {busy === d.email ? <LoaderCircle size={16} className="spin" /> : <ArrowRight size={16} />}
                </button>
              ))}
              <div className="tiny muted row" style={{ gap: 6 }}>
                <BadgeCheck size={14} /> Passwords are hashed (PBKDF2) and sessions use an httpOnly cookie.
              </div>
            </div>
          )}
        </form>
      </section>
    </div>
  )
}
