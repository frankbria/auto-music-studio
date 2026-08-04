"use client"

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react"

import { useAuth } from "@/hooks/use-auth"
import { CreditsError, fetchBalance, type CreditBalance } from "@/lib/credits"

/**
 * The signed-in musician's credit balance (US-26.1).
 *
 * Lives in the ROOT layout because the balance renders in the Sidebar on every page
 * while the actions that *spend* credits live all over the app — both need one
 * reactive source, exactly like the notifications unread count.
 *
 * `refresh()` is what makes it update "after each action": a hook that has just
 * submitted or completed a billed job calls it, rather than every page polling.
 */

export type CreditsState =
  | { phase: "loading" }
  | { phase: "ready"; balance: CreditBalance }
  /** No access token — signed out, or a refresh that failed. Distinct from an error
      so the sidebar can simply show nothing rather than a red failure. */
  | { phase: "signed-out" }
  | { phase: "error"; message: string }

type CreditsContextValue = {
  state: CreditsState
  /** Re-read the balance from the server. Safe to call from anywhere, any number of times. */
  refresh: () => void
}

const CreditsContext = createContext<CreditsContextValue | null>(null)

export function CreditsProvider({ children }: { children: React.ReactNode }) {
  const { accessToken } = useAuth()
  const [state, setState] = useState<CreditsState>({ phase: "loading" })
  const [nonce, setNonce] = useState(0)

  // The access token rotates mid-session, so a ref keeps `refresh` stable rather
  // than re-creating it (and re-running every dependent effect) on every rotation.
  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  const refresh = useCallback(() => setNonce((n) => n + 1), [])

  useEffect(() => {
    let cancelled = false

    const load = async () => {
      const token = tokenRef.current

      if (!token) {
        // Drops the balance as well as stopping the spinner: a cleared token must
        // not leave the previous user's number on screen.
        if (!cancelled) setState({ phase: "signed-out" })
        return
      }

      try {
        const balance = await fetchBalance(token)
        if (!cancelled) setState({ phase: "ready", balance })
      } catch (error) {
        if (cancelled) return
        setState({
          phase: "error",
          message:
            error instanceof CreditsError
              ? error.message
              : "Could not load your credit balance.",
        })
      }
    }

    void load()

    return () => {
      cancelled = true
    }
  }, [nonce, accessToken])

  const value = useMemo(() => ({ state, refresh }), [state, refresh])

  return (
    <CreditsContext.Provider value={value}>{children}</CreditsContext.Provider>
  )
}

/**
 * Read the balance, and get a way to re-read it.
 *
 * Returns a no-op `refresh` outside the provider so a component that merely *spends*
 * credits does not have to care whether it is mounted under one — that would make
 * every billed hook conditional on layout.
 */
export function useCredits(): CreditsContextValue {
  const ctx = useContext(CreditsContext)
  return ctx ?? FALLBACK
}

const FALLBACK: CreditsContextValue = {
  state: { phase: "signed-out" },
  refresh: () => {},
}
