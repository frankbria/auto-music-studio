"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import {
  fetchMasteringHistory,
  type MasteringHistoryItem,
} from "@/lib/mastering"

export type MasteringHistoryState =
  | { status: "loading" }
  | { status: "ready"; jobs: MasteringHistoryItem[] }
  | { status: "error" }

/** Fetch outcome tagged with whose list it is (user + clip), so a different
 *  clip or a different signed-in user never sees it. */
type Outcome =
  | { key: string; kind: "ready"; jobs: MasteringHistoryItem[] }
  | { key: string; kind: "error" }

export type UseMasteringHistory = {
  state: MasteringHistoryState
  reload: () => void
}

/**
 * The selected song's mastering jobs (#738). Re-fetches when the clip, the
 * signed-in user or `refreshKey` changes (the tab passes its job/approval phase,
 * so a new job or approval shows up). Another clip's or another user's list
 * reads as "loading", while a refresh of the same list keeps it on screen until
 * the new one lands. Keyed on the user id, not the token, so a token refresh
 * doesn't refetch.
 */
export function useMasteringHistory(
  clipId: string | undefined,
  refreshKey?: string
): UseMasteringHistory {
  const { accessToken, user } = useAuth()
  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])
  const key = clipId && user ? `${user.id}:${clipId}` : null

  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!key || !clipId || !tokenRef.current) return
    const ctl = new AbortController()
    fetchMasteringHistory(clipId, tokenRef.current)
      .then((jobs) => {
        if (ctl.signal.aborted) return
        setOutcome(jobs ? { key, kind: "ready", jobs } : { key, kind: "error" })
      })
      .catch(() => {
        if (!ctl.signal.aborted) setOutcome({ key, kind: "error" })
      })
    return () => ctl.abort()
  }, [key, clipId, nonce, refreshKey])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  const current = key !== null && outcome?.key === key ? outcome : null
  if (!current) return { state: { status: "loading" }, reload }
  if (current.kind === "error") return { state: { status: "error" }, reload }
  return { state: { status: "ready", jobs: current.jobs }, reload }
}
