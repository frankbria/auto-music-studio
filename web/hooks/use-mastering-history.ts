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

/** Whose list the hook shows: null until there is both a song and a signed-in user. */
function historyKey(
  clipId: string | undefined,
  userId: string | undefined
): string | null {
  return clipId && userId ? `${userId}:${clipId}` : null
}

/** Fetch one list, folding a failure into an error outcome tagged with `key`. */
async function loadHistory(
  clipId: string,
  token: string,
  key: string
): Promise<Outcome> {
  const jobs = await fetchMasteringHistory(clipId, token).catch(() => null)
  return jobs ? { key, kind: "ready", jobs } : { key, kind: "error" }
}

/** The state to show: only an outcome for the current key counts. */
function historyState(
  outcome: Outcome | null,
  key: string | null
): MasteringHistoryState {
  if (key === null || outcome?.key !== key) return { status: "loading" }
  return outcome.kind === "ready"
    ? { status: "ready", jobs: outcome.jobs }
    : { status: "error" }
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
  const key = historyKey(clipId, user?.id)

  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    const token = tokenRef.current
    if (!key || !clipId || !token) return
    const ctl = new AbortController()
    void loadHistory(clipId, token, key).then((next) => {
      if (!ctl.signal.aborted) setOutcome(next)
    })
    return () => ctl.abort()
  }, [key, clipId, nonce, refreshKey])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { state: historyState(outcome, key), reload }
}
