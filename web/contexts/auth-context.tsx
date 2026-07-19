"use client"

import {
  createContext,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import { useRouter } from "next/navigation"

import { decodeAccessToken, decodeTokenExp, type AuthUser } from "@/lib/auth"

// Refresh this long before the access token's `exp` so a renewed token is in
// hand before the old one dies. Also the "near expiry" window the visibility
// listener uses to decide a returning tab needs a fresh token.
// ponytail: 60s comfortably clears background-tab timer throttling (~1/min);
// widen if a shorter access-token lifetime makes it cut too close.
const REFRESH_SKEW_MS = 60_000

// After a *transient* refresh failure (5xx/429/network) the token is still
// valid for up to REFRESH_SKEW_MS, so retry soon rather than let it expire.
const REFRESH_RETRY_MS = 15_000

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

  // Rotate the access token via the refresh cookie. Single-flight: concurrent
  // callers (the scheduled refresh-ahead and the visibility listener) share one
  // request so they can't race the backend's single-use refresh token into
  // revocation (#285). Returns the new token, or null if none was obtained.
  //
  // 401/403 means the refresh token is gone/revoked → the session is
  // unrecoverable, so clear the access token: `isAuthenticated` flips false and
  // useRequireAuth redirects to /login. Any other failure (5xx, 429, network)
  // is transient — keep the current token and let the caller retry; signing out
  // a valid user on a backend blip would be worse than the blip.
  const refreshing = useRef<Promise<string | null> | null>(null)
  const refresh = useCallback((): Promise<string | null> => {
    if (refreshing.current) return refreshing.current
    const inflight = fetch("/api/auth/refresh", { method: "POST" })
      .then(async (res) => {
        if (res.status === 401 || res.status === 403) {
          setAccessToken(null)
          return null
        }
        if (!res.ok) return null
        const { access_token } = (await res.json()) as { access_token?: string }
        setAccessToken(access_token ?? null)
        return access_token ?? null
      })
      .catch(() => null)
      .finally(() => {
        refreshing.current = null
      })
    refreshing.current = inflight
    return inflight
  }, [])

  // On mount, restore a session via the refresh cookie.
  useEffect(() => {
    let active = true
    refresh().finally(() => {
      if (active) setIsLoading(false)
    })
    return () => {
      active = false
    }
  }, [refresh])

  // Refresh-ahead: schedule a renewal ~REFRESH_SKEW_MS before the current
  // token's `exp`. A token already past expiry isn't scheduled here (a returning
  // tab or the retry chain below recovers it) — this avoids a busy-loop if the
  // backend ever hands back a stale token.
  useEffect(() => {
    if (!accessToken) return
    const exp = decodeTokenExp(accessToken)
    if (exp === null || exp <= Date.now()) return
    let timer: ReturnType<typeof setTimeout>
    const run = async () => {
      // A successful refresh rotates the token, re-running this effect to
      // schedule the next renewal. A transient failure leaves the token
      // unchanged (no re-run), so re-arm a short retry rather than let it die.
      const rotated = await refresh()
      if (!rotated) timer = setTimeout(run, REFRESH_RETRY_MS)
    }
    timer = setTimeout(run, Math.max(0, exp - REFRESH_SKEW_MS - Date.now()))
    return () => clearTimeout(timer)
  }, [accessToken, refresh])

  // A backgrounded tab throttles timers, so the scheduled refresh can fire late.
  // When such a tab comes back, renew immediately if the token is missing its
  // safety window — covers "tab left open past the token lifetime" (#285).
  useEffect(() => {
    function onVisible() {
      if (document.visibilityState !== "visible" || !accessToken) return
      const exp = decodeTokenExp(accessToken)
      if (exp !== null && exp - REFRESH_SKEW_MS > Date.now()) return
      refresh()
    }
    document.addEventListener("visibilitychange", onVisible)
    return () => document.removeEventListener("visibilitychange", onVisible)
  }, [accessToken, refresh])

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
