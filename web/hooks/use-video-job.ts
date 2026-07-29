"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"

import { useAuth } from "@/hooks/use-auth"
import {
  fetchVideoStatus,
  submitVideoJob,
  type VideoConfig,
  type VideoStatusDetail,
} from "@/lib/video"

const POLL_INTERVAL_MS = 2500
// Cap polling so a stuck/vanished job surfaces an error instead of spinning
// forever. Renders run minutes to tens of minutes, so the cap is generous:
// 720 × 2.5s = 30 min. ponytail: fixed cap; US-22.3's richer progress view can
// revisit if real renders run longer.
const MAX_POLLS = 720

/** The video job state machine: idle → submitting → polling → complete|error. */
export type VideoJobState =
  | { phase: "idle" }
  | { phase: "submitting" }
  // `jobId` is known the moment the 202 lands (before the first poll), so the
  // app-level VideoJobsProvider can start watching it for the completion
  // notification even if the user navigates away immediately (US-22.3 AC2).
  | { phase: "polling"; jobId: string; detail?: VideoStatusDetail }
  | { phase: "complete"; detail: VideoStatusDetail }
  | { phase: "error"; message: string }

export type UseVideoJob = {
  state: VideoJobState
  /** Submit a video job for a clip and drive it to completion. */
  submit: (clipId: string, config: VideoConfig) => Promise<void>
  /** Re-run the last submit (for the error/failed state's Retry). No-op if none. */
  retry: () => void
  /** Clear back to idle (start a new render after completing/failing). */
  reset: () => void
}

/**
 * Owns one video render's lifecycle (US-22.2). After the 202 it polls the job
 * through the BFF proxy until complete/failed, surfacing the live progress
 * detail for the progress view. The access token is read from auth context and
 * kept in a ref (it rotates mid-session, #285) so the poll loop always uses the
 * latest without re-subscribing. Mirrors use-mastering-job.
 */
export function useVideoJob(): UseVideoJob {
  const router = useRouter()
  const { accessToken } = useAuth()
  const [state, setState] = useState<VideoJobState>({ phase: "idle" })

  const tokenRef = useRef(accessToken)
  useEffect(() => {
    tokenRef.current = accessToken
  }, [accessToken])

  // The active job. A ref (not state) so the poll loop reads the latest without
  // re-subscribing; cleared the moment the job is superseded or terminal.
  const jobRef = useRef<{ id: string; polls: number } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // The last submission's args, so Retry can replay it verbatim.
  const lastArgsRef = useRef<{ clipId: string; config: VideoConfig } | null>(null)

  // Holds the latest `poll` so the scheduled timeout can call it without `poll`
  // referencing itself (hook-immutability lint forbids that).
  const pollRef = useRef<() => void>(() => {})

  // False once unmounted. Both the poll's and the submit's fetches resolve
  // asynchronously; either can land after the component is gone, so every
  // post-await branch checks this before it setState/arms a timer/kicks a poll.
  const mountedRef = useRef(true)

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  // Clean up on unmount: mark unmounted, cancel any pending poll, drop the job.
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      clearTimer()
      jobRef.current = null
    }
  }, [])

  const poll = useCallback(async () => {
    const job = jobRef.current
    if (!job) return
    const result = await fetchVideoStatus(job.id, tokenRef.current ?? "")
    if (!mountedRef.current) return
    // A reset/retry between the request and its response supersedes this job.
    if (jobRef.current?.id !== job.id) return

    switch (result.kind) {
      case "complete":
        jobRef.current = null
        clearTimer()
        setState({ phase: "complete", detail: result.detail })
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
          setState({
            phase: "error",
            message: "Video generation timed out. Please try again.",
          })
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
    async (clipId: string, config: VideoConfig) => {
      lastArgsRef.current = { clipId, config }
      clearTimer()
      jobRef.current = null
      setState({ phase: "submitting" })

      const result = await submitVideoJob(clipId, config, tokenRef.current ?? "")
      // Bail if the page unmounted while the POST was in flight — otherwise the
      // accepted branch would re-arm jobRef + a poll loop on a dead component.
      if (!mountedRef.current) return
      switch (result.status) {
        case "accepted":
          jobRef.current = { id: result.jobId, polls: 0 }
          setState({ phase: "polling", jobId: result.jobId })
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
        case "unavailable":
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
