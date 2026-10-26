import { useEffect, useRef, useState, type ComponentType, type ReactNode } from 'react'
import { Activity, FilePlus2, FlaskConical, Gauge, Hourglass, House, Layers, LoaderCircle, LogOut, Settings2, ShieldCheck, Sparkles, Swords, TrendingUp, Users, Workflow, type LucideProps } from 'lucide-react'
import { api } from './api'
import { AuthProvider, can, useAuth, type CAN, type User } from './auth'
import { BrandMark } from './brand'
import { CopilotDock, CopilotProvider } from './copilot'
import { fmtDate, useRoute } from './lib'
import type { Meta } from './types'
import NewDeal from './pages/NewDeal'
import DealView from './pages/DealView'
import Deals from './pages/Deals'
import Staffing from './pages/Staffing'
import UsagePage from './pages/Usage'
import CopilotPage from './pages/Copilot'
import Login from './pages/Login'
import HomePage from './pages/Home'
import Bench from './pages/Bench'
import Appraisals from './pages/Appraisals'
import ScopeGuard from './pages/ScopeGuard'
import ProjectHealth from './pages/ProjectHealth'
import ActivityPage from './pages/Activity'
import DealRoomPage from './pages/DealRoomPage'
import EvaluationPage from './pages/Evaluation'
import SettingsPage from './pages/Settings'

type NavItem = {
  path: string
  label: string
  icon: ComponentType<LucideProps>
  area: keyof typeof CAN
  page: (route: string[], meta: Meta | null) => ReactNode
}

const NAV: { group: string; items: NavItem[] }[] = [
  {
    group: 'Overview',
    items: [{ path: 'home', label: 'Home', icon: House, area: 'home', page: () => <HomePage /> }],
  },
  {
    group: 'Sales',
    items: [
      { path: 'new', label: 'Deal Desk', icon: FilePlus2, area: 'deals', page: (_r, m) => <NewDeal meta={m} /> },
      { path: 'deals', label: 'Deals', icon: Layers, area: 'deals', page: (r) => (r[1] ? <DealView id={r[1]} /> : <Deals />) },
      { path: 'room', label: 'Deal Room', icon: Swords, area: 'room', page: () => <DealRoomPage /> },
    ],
  },
  {
    group: 'Delivery',
    items: [
      { path: 'scope', label: 'Scope Guard', icon: ShieldCheck, area: 'scope', page: () => <ScopeGuard /> },
      { path: 'projects', label: 'Project Health', icon: Activity, area: 'projects', page: (r) => <ProjectHealth code={r[1]} /> },
    ],
  },
  {
    group: 'People',
    items: [
      { path: 'staffing', label: 'Staffing', icon: Users, area: 'staffing', page: () => <Staffing /> },
      { path: 'bench', label: 'Bench Optimizer', icon: Hourglass, area: 'bench', page: () => <Bench /> },
      { path: 'appraisals', label: 'Appraisals & hikes', icon: TrendingUp, area: 'appraisals', page: () => <Appraisals /> },
    ],
  },
  {
    group: 'Intelligence',
    items: [
      { path: 'copilot', label: 'Emi', icon: Sparkles, area: 'copilot', page: () => <CopilotPage /> },
      { path: 'activity', label: 'Agent Activity', icon: Workflow, area: 'activity', page: (r) => <ActivityPage id={r[1]} /> },
    ],
  },
  {
    group: 'Administration',
    items: [
      { path: 'usage', label: 'Usage & safety', icon: Gauge, area: 'usage', page: (_r, m) => <UsagePage meta={m} /> },
      { path: 'evaluation', label: 'Evaluation', icon: FlaskConical, area: 'evaluation', page: () => <EvaluationPage /> },
      { path: 'settings', label: 'Settings', icon: Settings2, area: 'settings', page: () => <SettingsPage /> },
    ],
  },
]

export default function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  )
}

function Gate() {
  const { user, checking } = useAuth()
  if (checking)
    return (
      <div className="center-screen">
        <LoaderCircle className="spin" />
      </div>
    )
  if (!user) return <Login />
  return (
    <CopilotProvider key={user.id}>
      <Shell user={user} />
    </CopilotProvider>
  )
}

function Shell({ user }: { user: User }) {
  const route = useRoute()
  const { signOut } = useAuth()
  const [meta, setMeta] = useState<Meta | null>(null)

  useEffect(() => {
    api.get<Meta>('/api/meta').then(setMeta).catch(() => setMeta(null))
  }, [])

  const allowed = NAV.flatMap((g) => g.items).filter((i) => can(user, i.area))
  const current = allowed.find((i) => i.path === (route[0] ?? '')) ?? null
  // Land each role on its first page; a path the role can't open falls back to it too.
  useEffect(() => {
    if (!current && allowed.length) window.location.hash = `/${allowed[0].path}`
  }, [current, allowed])

  const pageDealId = route[0] === 'deals' && route[1] ? route[1] : null
  // Each page gets its own key so it re-mounts with the enter animation; scroll starts at the top.
  const pageKey = route.slice(0, 2).join('/') || 'home'
  const mainRef = useRef<HTMLElement>(null)
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0 })
  }, [pageKey])
  const initials = user.name.split(' ').map((x) => x[0]).join('').slice(0, 2)

  return (
    <div className="app">
      <aside className="sidebar">
        <a className="brand" href={`#/${allowed[0]?.path ?? ''}`}>
          <BrandMark />
          <div>
            <div className="brand-name">Empower Ops Agents</div>
            <div className="brand-sub">for Empower Solutions</div>
          </div>
        </a>

        {NAV.map((g) => {
          const items = g.items.filter((i) => can(user, i.area))
          if (!items.length) return null
          return (
            <nav className="nav-section" key={g.group}>
              {g.group !== 'Overview' && <div className="nav-label">{g.group}</div>}
              {items.map((n) => {
                const Icon = n.icon
                return (
                  <a key={n.path} href={`#/${n.path}`} className={`nav-item ${current?.path === n.path ? 'active' : ''}`}>
                    <Icon size={17} strokeWidth={2} />
                    {n.label}
                  </a>
                )
              })}
            </nav>
          )
        })}

        <div className="sidebar-foot">
          <div className="foot-row">
            <span>Model</span>
            <b className="mono">{meta?.model ?? '…'}</b>
          </div>
          <div className="foot-row">
            <span>Data</span>
            <b>{meta ? (meta.dataset.synthetic ? `Synthetic · ${fmtDate(meta.dataset.as_of)}` : 'Company data') : '…'}</b>
          </div>
          {meta && !meta.api_key_present && (
            <div className="notice red tiny">No PORTKEY_API_KEY found. Add it to .env in this folder or the one above.</div>
          )}
          <div className="user-card">
            <span className="avatar me">{initials}</span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="strong small">{user.name}</div>
              <div className="tiny muted">{user.role_label}</div>
            </div>
            <button className="icon-btn" title="Sign out" onClick={() => void signOut()}>
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>
      <main className="main" ref={mainRef}>
        <div key={pageKey} className="page-anim">
          {current ? current.page(route, meta) : null}
        </div>
        {can(user, 'copilot') && route[0] !== 'copilot' && <CopilotDock pageDealId={pageDealId} />}
      </main>
    </div>
  )
}
