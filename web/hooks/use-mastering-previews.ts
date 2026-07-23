"use client"

import { useCallback, useEffect, useRef, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { fetchMasteringPreviews, type PreviewsResponse } from "@/lib/mastering"

export type PreviewsState =
  | { status: "loading" }
  | { status: "ready"; data: PreviewsResponse }
  | { status: "error" }

/** Fetch outcome tagged with the job id it belongs to (mirrors useClipAudio). */
type Outcome =
  | { jobId: string; kind: "ready"; data: PreviewsResponse }
  | { jobId: string; kind: "error" }

export type UseMasteringPreviews = {
  state: PreviewsState
  /** The effective selected preview id: the user's pick, or the first preview. */
  selectedId: string | null
  select: (previewId: string) => void
  /** Re-fetch (e.g. after a transient error). */
  reload: () => void
}

/**
 * Fetch and manage the A/B preview set for a completed mastering job (US-21.2).
 * Re-fetches when the job id changes; the in-flight request is aborted on
 * change/unmount and its outcome is tagged with the job id, so a stale response
 * reads as "loading" under a new id (no flash, no synchronous reset).
 *
 * The selected preview is *derived* (explicit pick ?? first preview) rather than
 * stored, so there's no set-state-in-effect when previews load and the first
 * candidate is always auditioned by default.
 */
export function useMasteringPreviews(
  jobId: string | undefined
): UseMasteringPreviews {
  const { accessToken } = useAuth()
  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])
  const hasToken = accessToken !== null

  const [outcome, setOutcome] = useState<Outcome | null>(null)
  const [explicitId, setExplicitId] = useState<string | null>(null)
  // Bumped by reload() to retrigger the fetch effect on demand.
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    if (!jobId || !tokenRef.current) return
    const ctl = new AbortController()
    fetchMasteringPreviews(jobId, tokenRef.current)
      .then((data) => {
        if (ctl.signal.aborted) return
        setOutcome(
          data
            ? { jobId, kind: "ready", data }
            : { jobId, kind: "error" }
        )
      })
      .catch(() => {
        if (!ctl.signal.aborted) setOutcome({ jobId, kind: "error" })
      })
    return () => ctl.abort()
  }, [jobId, hasToken, nonce])

  const select = useCallback((previewId: string) => setExplicitId(previewId), [])
  const reload = useCallback(() => setNonce((n) => n + 1), [])

  const current = outcome?.jobId === jobId ? outcome : null
  if (!current) {
    return { state: { status: "loading" }, selectedId: null, select, reload }
  }
  if (current.kind === "error") {
    return { state: { status: "error" }, selectedId: null, select, reload }
  }

  const previews = current.data.previews
  // The user's pick wins if it's still in the set; otherwise the first candidate
  // is auditioned by default (derived, not stored — no set-state-in-effect).
  const selectedId =
    (explicitId && previews.some((p) => p.preview_id === explicitId)
      ? explicitId
      : previews[0]?.preview_id) ?? null

  return { state: { status: "ready", data: current.data }, selectedId, select, reload }
}
