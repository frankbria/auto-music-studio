"use client"

import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"
import { useRouter } from "next/navigation"

import { decodeAccessToken, type AuthUser } from "@/lib/auth"

type AuthContextValue = {
  user: AuthUser | null
  /** In-memory access token for same-origin Bearer calls (e.g. /api/users/me). */
  accessToken: string | null
  isAuthenticated: boolean
  isLoading: boolean
  /** Begin an OAuth flow; redirects the browser to the provider on success. */
  login: (provider: string) => Promise<void>
  /** Exchange an OAuth callback's code/state for a session. */
  completeLogin: (provider: string, code: string, state: string) => Promise<void>
  logout: () => Promise<void>
}

export const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter()
  // Access token lives in memory only — never localStorage. The refresh token
  // is held server-side in an httpOnly cookie by the BFF.
  const [accessToken, setAccessToken] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // On mount, try to restore a session via the refresh cookie.
  useEffect(() => {
    let active = true
    fetch("/api/auth/refresh", { method: "POST" })
      .then(async (res) => {
        if (active && res.ok) {
          const { access_token } = await res.json()
          setAccessToken(access_token)
        }
      })
      .catch(() => {})
      .finally(() => {
        if (active) setIsLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

  const login = useCallback(async (provider: string) => {
    const res = await fetch(`/api/auth/login/${provider}`, { method: "POST" })
    if (!res.ok) throw new Error("Failed to start login.")
    const { authorization_url } = await res.json()
    window.location.assign(authorization_url)
  }, [])

  const completeLogin = useCallback(
    async (provider: string, code: string, state: string) => {
      const res = await fetch(`/api/auth/callback/${provider}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ code, state }),
      })
      if (!res.ok) throw new Error("Authentication failed.")
      const { access_token } = await res.json()
      setAccessToken(access_token)
    },
    []
  )

  const logout = useCallback(async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {})
    setAccessToken(null)
    router.push("/login")
  }, [router])

  const value = useMemo<AuthContextValue>(() => {
    // Derive isAuthenticated from the decoded user so the two can't disagree
    // (a token missing sub/email decodes to null → treated as unauthenticated).
    const user = accessToken ? decodeAccessToken(accessToken) : null
    return {
      user,
      accessToken,
      isAuthenticated: user !== null,
      isLoading,
      login,
      completeLogin,
      logout,
    }
  }, [accessToken, isLoading, login, completeLogin, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
