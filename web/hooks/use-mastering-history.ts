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

/** Fetch outcome tagged with the clip it belongs to (mirrors useMasteringPreviews). */
type Outcome =
  | { clipId: string; kind: "ready"; jobs: MasteringHistoryItem[] }
  | { clipId: string; kind: "error" }

export type UseMasteringHistory = {
  state: MasteringHistoryState
  reload: () => void
}

/**
 * The selected song's mastering jobs (#738). Re-fetches when the clip or
 * `refreshKey` changes (the tab passes its job/approval phase, so a new job or
 * approval shows up). The outcome is tagged with the clip id: another clip's
 * list reads as "loading", while a refresh of the same clip keeps the last list
 * on screen until the new one lands.
 */
export function useMasteringHistory(
  clipId: string | undefined,
  refreshKey?: string
): UseMasteringHistory {
  const { accessToken } = useAuth()
  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])
  const hasToken = accessToken !== null

  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!clipId || !tokenRef.current) return
    const ctl = new AbortController()
    fetchMasteringHistory(clipId, tokenRef.current)
      .then((jobs) => {
        if (ctl.signal.aborted) return
        setOutcome(
          jobs ? { clipId, kind: "ready", jobs } : { clipId, kind: "error" }
        )
      })
      .catch(() => {
        if (!ctl.signal.aborted) setOutcome({ clipId, kind: "error" })
      })
    return () => ctl.abort()
  }, [clipId, hasToken, nonce, refreshKey])

  const reload = useCallback(() => setNonce((n) => n + 1), [])

  const current = outcome?.clipId === clipId ? outcome : null
  if (!current) return { state: { status: "loading" }, reload }
  if (current.kind === "error") return { state: { status: "error" }, reload }
  return { state: { status: "ready", jobs: current.jobs }, reload }
}
