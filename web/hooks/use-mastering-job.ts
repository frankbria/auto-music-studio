"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"

import { useAuth } from "@/hooks/use-auth"
import {
  fetchMasteringStatus,
  submitMasteringJob,
  type MasteringConfig,
  type MasteringJobDetail,
} from "@/lib/mastering"

const POLL_INTERVAL_MS = 2500
// Cap polling so a stuck/vanished job surfaces an error instead of spinning
// forever. 240 × 2.5s = 10 min — mastering estimate is ~60s, so this is ample
// headroom. ponytail: fixed cap; raise if real masters ever run longer.
const MAX_POLLS = 240

/** The mastering job state machine: idle → submitting → polling → completed|error. */
export type MasteringJobState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "polling"; detail?: MasteringJobDetail }
  | { phase: "completed"; detail: MasteringJobDetail }
  | { phase: "error"; message: string }

export type UseMasteringJob = {
  state: MasteringJobState
  /** Submit a mastering job for a clip and drive it to completion. */
  submit: (clipId: string, config: MasteringConfig) => Promise<void>
  /** Re-run the last submit (for the error/failed state's Retry). No-op if none. */
  retry: () => void
  /** Clear back to idle (start a new master after completing/failing). */
  reset: () => void
}

/**
 * Owns one mastering job's lifecycle (US-21.2). After the 202 it polls the job
 * through the BFF proxy until completed/failed, then surfaces the completed
 * detail so the tab can load previews. The access token is read from auth
 * context and kept in a ref (it rotates mid-session, #285) so the poll loop
 * always uses the latest without re-subscribing. Mirrors use-generation.
 */
export function useMasteringJob({
  onComplete,
}: { onComplete?: (detail: MasteringJobDetail) => void } = {}): UseMasteringJob {
  const router = useRouter()
  const { accessToken } = useAuth()
  const [state, setState] = useState<MasteringJobState>({ phase: "idle" })

  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  // The active job. A ref (not state) so the poll loop reads the latest without
  // re-subscribing; cleared the moment the job is superseded or terminal.
  const jobRef = useRef<{ id: string; polls: number } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // The last submission's args, so Retry can replay it verbatim.
  const lastArgsRef = useRef<{ clipId: string; config: MasteringConfig } | null>(null)
  const onCompleteRef = useRef(onComplete)
  useEffect(() => {
    onCompleteRef.current = onComplete
  })

  // Holds the latest `poll` so the scheduled timeout can call it without `poll`
  // referencing itself (hook-immutability lint forbids that).
  const pollRef = useRef<() => void>(() => {})

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  // Clean up on unmount. Nulling jobRef (not just clearing the timer) is what
  // stops an *in-flight* poll from rescheduling itself after unmount: with no
  // active job the poll's supersession guard short-circuits before it can
  // setState or arm a new timer, so no orphaned polling survives navigation.
  useEffect(
    () => () => {
      clearTimer()
      jobRef.current = null
    },
    []
  )

  const poll = useCallback(async () => {
    const job = jobRef.current
    if (!job) return
    const result = await fetchMasteringStatus(job.id, tokenRef.current ?? "")
    // A reset/retry between the request and its response supersedes this job.
    if (jobRef.current?.id !== job.id) return

    switch (result.kind) {
      case "completed":
        jobRef.current = null
        clearTimer()
        setState({ phase: "completed", detail: result.detail })
        onCompleteRef.current?.(result.detail)
        return
      case "failed":
        jobRef.current = null
        clearTimer()
        setState({ phase: "error", message: result.error })
        return
      case "unauthorized":
        jobRef.current = null
        clearTimer()
        router.push("/login")
        return
      case "pending":
      case "transient":
        job.polls += 1
        if (job.polls >= MAX_POLLS) {
          jobRef.current = null
          clearTimer()
          setState({ phase: "error", message: "Mastering timed out. Please try again." })
          return
        }
        if (result.kind === "pending") {
          const { detail } = result
          setState((s) => (s.phase === "polling" ? { ...s, detail } : s))
        }
        timerRef.current = setTimeout(() => pollRef.current(), POLL_INTERVAL_MS)
        return
    }
  }, [router])

  useEffect(() => {
    pollRef.current = poll
  }, [poll])

  const submit = useCallback(
    async (clipId: string, config: MasteringConfig) => {
      lastArgsRef.current = { clipId, config }
      clearTimer()
      jobRef.current = null
      setState({ phase: "submitting" })

      const result = await submitMasteringJob(clipId, config, tokenRef.current ?? "")
      switch (result.status) {
        case "accepted":
          jobRef.current = { id: result.jobId, polls: 0 }
          setState({ phase: "polling" })
          // Poll immediately so a fast job doesn't sit idle for the first interval.
          void poll()
          return
        case "unauthorized":
          router.push("/login")
          return
        case "insufficient_credits":
          setState({
            phase: "error",
            message: `Not enough credits — ${result.required} required, ${result.balance} available.`,
          })
          return
        case "invalid":
        case "error":
          setState({ phase: "error", message: result.detail })
          return
      }
    },
    [poll, router]
  )

  const retry = useCallback(() => {
    const args = lastArgsRef.current
    if (args) void submit(args.clipId, args.config)
  }, [submit])

  const reset = useCallback(() => {
    clearTimer()
    jobRef.current = null
    setState({ phase: "idle" })
  }, [])

  return { state, submit, retry, reset }
}
