"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"

import { fetchJobStatus } from "@/lib/job-status"
import type { SubmitResult } from "@/lib/generate"

const POLL_INTERVAL_MS = 2000
// Cap polling so a stuck or vanished job surfaces an error instead of spinning
// forever. 150 × 2s ≈ 5 min — well past the slowest model's estimate (XL ~30-60s).
// ponytail: fixed cap; raise if real jobs ever run longer than this.
const MAX_POLLS = 150

/** The creation flow's state machine: idle → submitting → polling → success|error. */
export type GenerationState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "polling"; estimatedSeconds: number; progress?: string }
  | { phase: "success"; clipIds: string[] }
  | { phase: "error"; message: string }

/** A per-form closure that builds + submits the request, returning the 202 result. */
export type SubmitFn = () => Promise<SubmitResult>

export type UseGeneration = {
  state: GenerationState
  /** Submit a request and drive it to completion. `accessToken` is reused for polling. */
  submit: (makeRequest: SubmitFn, accessToken: string) => Promise<void>
  /** Re-run the last submit (for the error state's Retry). No-op if nothing was submitted. */
  retry: () => void
  /** Clear back to idle (dismiss an error / reset after success). */
  reset: () => void
}

/**
 * Owns one creation's lifecycle (US-16.7). After the 202 it polls the job through
 * the BFF proxy until completed/failed, exposing progress + the backend's
 * model-aware time estimate, and calls `onComplete` once clips exist so the
 * caller can refresh the workspace. Each of the three creation forms uses its own
 * instance; the form supplies the request builder so per-tab payloads stay local.
 */
export function useGeneration({
  onComplete,
}: { onComplete?: () => void } = {}): UseGeneration {
  const router = useRouter()
  const [state, setState] = useState<GenerationState>({ phase: "idle" })

  // The active job. A ref (not state) so the poll loop reads the latest without
  // re-subscribing; cleared the moment the job is superseded or terminal.
  const jobRef = useRef<{ id: string; token: string; polls: number } | null>(
    null
  )
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // The last submission's args, stored so Retry can replay it verbatim.
  const lastArgsRef = useRef<{
    makeRequest: SubmitFn
    accessToken: string
  } | null>(null)
  // Held in a ref so the poll loop's identity doesn't churn with the callback.
  const onCompleteRef = useRef(onComplete)
  useEffect(() => {
    onCompleteRef.current = onComplete
  })

  // Holds the latest `poll` so the scheduled timeout can call it without `poll`
  // referencing itself (which the hook-immutability lint forbids).
  const pollRef = useRef<() => void>(() => {})

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  // Clean up a pending poll if the component unmounts mid-generation.
  useEffect(() => clearTimer, [])

  const poll = useCallback(async () => {
    const job = jobRef.current
    if (!job) return
    const result = await fetchJobStatus(job.id, job.token)
    // A reset/retry between the request and its response supersedes this job.
    if (jobRef.current?.id !== job.id) return

    switch (result.kind) {
      case "completed":
        jobRef.current = null
        clearTimer()
        setState({ phase: "success", clipIds: result.clipIds })
        onCompleteRef.current?.()
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
            message: "Generation timed out. Please try again.",
          })
          return
        }
        if (result.kind === "pending" && result.progress) {
          const { progress } = result
          setState((s) => (s.phase === "polling" ? { ...s, progress } : s))
        }
        timerRef.current = setTimeout(
          () => void pollRef.current(),
          POLL_INTERVAL_MS
        )
        return
    }
  }, [router])

  useEffect(() => {
    pollRef.current = poll
  })

  const submit = useCallback(
    async (makeRequest: SubmitFn, accessToken: string) => {
      lastArgsRef.current = { makeRequest, accessToken }
      clearTimer()
      jobRef.current = null
      setState({ phase: "submitting" })

      const result = await makeRequest()
      switch (result.status) {
        case "accepted":
          jobRef.current = { id: result.jobId, token: accessToken, polls: 0 }
          setState({
            phase: "polling",
            estimatedSeconds: result.estimatedSeconds,
          })
          // Poll immediately so a fast job doesn't sit idle for the first interval.
          void poll()
          return
        case "unauthorized":
          router.push("/login")
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
    if (args) void submit(args.makeRequest, args.accessToken)
  }, [submit])

  const reset = useCallback(() => {
    clearTimer()
    jobRef.current = null
    setState({ phase: "idle" })
  }, [])

  return { state, submit, retry, reset }
}
