import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import i18n from './i18n'
import { request, refreshAccessToken, setAccessToken, setLoggedOutHandler, type User } from './api/client'

type AuthState = {
  user: User | null
  ready: boolean
  login: (email: string, password: string, totp?: string) => Promise<void>
  logout: () => Promise<void>
  reloadUser: () => Promise<void>
}

const Ctx = createContext<AuthState | null>(null)
const IDLE_MS = 30 * 60 * 1000 // auto-logout after inactivity (Frontend.md §4)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)
  const qc = useQueryClient()

  const applyUser = (u: User | null) => {
    setUser(u)
    if (u?.locale && i18n.language !== u.locale) i18n.changeLanguage(u.locale)
  }

  const reloadUser = useCallback(async () => applyUser(await request<User>('GET', '/api/v1/me')), [])

  const logout = useCallback(async () => {
    try {
      await request('POST', '/api/v1/auth/logout')
    } catch {
      /* already logged out */
    }
    setAccessToken(null)
    setUser(null)
    qc.clear()
  }, [qc])

  useEffect(() => {
    setLoggedOutHandler(() => {
      setAccessToken(null)
      setUser(null)
    })
    ;(async () => {
      if (await refreshAccessToken()) {
        try {
          await reloadUser()
        } catch {
          /* ignore */
        }
      }
      setReady(true)
    })()
  }, [reloadUser])

  useEffect(() => {
    if (!user) return
    let timer = window.setTimeout(logout, IDLE_MS)
    const bump = () => {
      window.clearTimeout(timer)
      timer = window.setTimeout(logout, IDLE_MS)
    }
    const events = ['pointerdown', 'keydown', 'scroll']
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }))
    return () => {
      window.clearTimeout(timer)
      events.forEach((e) => window.removeEventListener(e, bump))
    }
  }, [user, logout])

  const login = async (email: string, password: string, totp?: string) => {
    const res = await request<{ access_token: string }>('POST', '/api/v1/auth/login', {
      email, password, totp: totp || null, client: 'web',
    })
    setAccessToken(res.access_token)
    await reloadUser()
  }

  return <Ctx.Provider value={{ user, ready, login, logout, reloadUser }}>{children}</Ctx.Provider>
}

export function useAuth(): AuthState {
  const v = useContext(Ctx)
  if (!v) throw new Error('AuthProvider missing')
  return v
}
