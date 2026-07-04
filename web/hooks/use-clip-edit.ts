"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"

import { fetchJobStatus } from "@/lib/job-status"
import type { EditSubmitResult } from "@/lib/editing"

const POLL_INTERVAL_MS = 2000
// Cap polling so a stuck/vanished job surfaces an error instead of spinning
// forever. 150 × 2s ≈ 5 min — past the slowest edit's estimate. Mirrors
// use-generation's cap.
const MAX_POLLS = 150

/** A single editing modal's lifecycle: idle → submitting → polling → success|error. */
export type ClipEditState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "polling"; estimatedSeconds: number; progress?: string }
  | { phase: "success"; clipIds: string[] }
  | { phase: "error"; message: string }

/** A per-modal closure that builds + submits the request, returning the result. */
export type ClipEditSubmitFn = () => Promise<EditSubmitResult>

export type UseClipEdit = {
  state: ClipEditState
  /** Submit an editing request and drive it to completion; `token` is reused for polling. */
  submit: (makeRequest: ClipEditSubmitFn, accessToken: string) => Promise<void>
  /** Clear back to idle (reset after success / dismiss an error). */
  reset: () => void
}

/**
 * Owns one editing operation's lifecycle for a workflow modal (US-17.3). After a
 * 202 it polls the job through the BFF proxy until completed/failed, exposing
 * progress so the modal can show a spinner, and surfacing the resulting
 * `clipIds` on success so the modal can offer a "View" link. Distinct from
 * `useGeneration` (which is coupled to the creation page's navigation): this is
 * self-contained so any modal can drop it in.
 */
export function useClipEdit(): UseClipEdit {
  const router = useRouter()
  const [state, setState] = useState<ClipEditState>({ phase: "idle" })

  // The active job, in a ref so the poll loop reads the latest without
  // re-subscribing; cleared the moment the job is superseded or terminal.
  const jobRef = useRef<{ id: string; token: string; polls: number } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Holds the latest `poll` so a scheduled timeout can call it without `poll`
  // referencing itself (hook-immutability lint forbids the self-reference).
  const pollRef = useRef<() => void>(() => {})

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }

  // Clean up if the modal unmounts mid-edit: clear the pending timer AND drop the
  // active job, so a fetchJobStatus already in flight can't pass the staleness
  // guard and reschedule another poll after the component is gone.
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
    const result = await fetchJobStatus(job.id, job.token)
    // A reset/retry between the request and its response supersedes this job.
    if (jobRef.current?.id !== job.id) return

    switch (result.kind) {
      case "completed":
        jobRef.current = null
        clearTimer()
        setState({ phase: "success", clipIds: result.clipIds })
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
            message: "This is taking longer than expected. Please try again.",
          })
          return
        }
        if (result.kind === "pending" && result.progress) {
          const { progress } = result
          setState((s) => (s.phase === "polling" ? { ...s, progress } : s))
        }
        timerRef.current = setTimeout(() => void pollRef.current(), POLL_INTERVAL_MS)
        return
    }
  }, [router])

  useEffect(() => {
    pollRef.current = poll
  })

  const submit = useCallback(
    async (makeRequest: ClipEditSubmitFn, accessToken: string) => {
      clearTimer()
      jobRef.current = null
      setState({ phase: "submitting" })

      const result = await makeRequest()
      switch (result.status) {
        case "accepted":
          jobRef.current = { id: result.jobId, token: accessToken, polls: 0 }
          setState({ phase: "polling", estimatedSeconds: result.estimatedSeconds })
          // Poll immediately so a fast job doesn't idle through the first interval.
          void poll()
          return
        case "unauthorized":
          router.push("/login")
          return
        case "insufficientCredits":
          setState({
            phase: "error",
            message: `Not enough credits — this needs ${result.required}, you have ${result.balance}.`,
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

  const reset = useCallback(() => {
    clearTimer()
    jobRef.current = null
    setState({ phase: "idle" })
  }, [])

  return { state, submit, reset }
}
