import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { api } from './api'

export type Role = 'director' | 'sales' | 'hr'
export type User = { id: number; email: string; name: string; role: Role; role_label: string }

type AuthState = {
  user: User | null
  checking: boolean
  signIn: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    api
      .get<User>('/api/auth/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setChecking(false))
    const onOut = () => setUser(null)
    window.addEventListener('empower:signed-out', onOut)
    return () => window.removeEventListener('empower:signed-out', onOut)
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    setUser(await api.post<User>('/api/auth/login', { email, password }))
  }, [])
  const signOut = useCallback(async () => {
    await api.post('/api/auth/logout', {}).catch(() => {})
    localStorage.removeItem('empower_copilot_chat')
    setUser(null)
  }, [])

  return <Ctx.Provider value={{ user, checking, signIn, signOut }}>{children}</Ctx.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthState {
  const c = useContext(Ctx)
  if (!c) throw new Error('useAuth must be used inside <AuthProvider>')
  return c
}

/** What each role can open. The server enforces the same rules; this only hides what would be refused. */
// eslint-disable-next-line react-refresh/only-export-components
export const CAN: Record<string, Role[]> = {
  home: ['director', 'sales', 'hr'],
  deals: ['director', 'sales'],
  copilot: ['director', 'sales'],
  scope: ['director', 'sales'],
  staffing: ['director', 'sales', 'hr'],
  bench: ['director', 'hr'],
  appraisals: ['director', 'hr'],
  usage: ['director', 'sales'],
  room: ['director', 'sales'],
  projects: ['director', 'sales'],
  activity: ['director', 'sales', 'hr'],
  evaluation: ['director', 'sales'],
  settings: ['director', 'sales', 'hr'],
}

// eslint-disable-next-line react-refresh/only-export-components
export const can = (user: User | null, area: keyof typeof CAN) => !!user && CAN[area].includes(user.role)
