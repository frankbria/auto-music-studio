"use client"

import { useCallback, useContext, useEffect, useRef } from "react"

import { AuthContext } from "@/contexts/auth-context"

/**
 * The viewer's token for discovery reads (#653), so the API can mark the viewer's own clips (`is_owner`).
 * `ready` waits for the session to resolve, so a page fetches once, with or without it. `token` reads the latest
 * value without being a dependency: a refreshed token must not re-run a search or reload a scrolled feed.
 * Discovery stays anonymous outside an AuthProvider.
 */
export function useDiscoveryAuth(): {
  ready: boolean
  token: () => string | null
} {
  const auth = useContext(AuthContext)
  const latest = useRef<string | null>(auth?.accessToken ?? null)
  useEffect(() => {
    latest.current = auth?.accessToken ?? null
  }, [auth?.accessToken])
  const token = useCallback(() => latest.current, [])
  return { ready: !auth?.isLoading, token }
}
