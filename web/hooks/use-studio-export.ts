"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useRouter } from "next/navigation"

import { fetchJobStatus } from "@/lib/job-status"
import type { MixdownRequestBody, StudioExportBody } from "@/lib/studio-export"

const POLL_INTERVAL_MS = 2000
// Cap polling so a stuck or vanished job surfaces an error instead of spinning
// forever. 150 × 2s ≈ 5 min — a mix/bounce of a full arrangement stays well
// inside this (mirrors use-generation's cap).
const MAX_POLLS = 150

const SUBMIT_FAILED = "Export failed. Please try again."
const SERVICE_DOWN = "Export service is unavailable."

/** Which export a running job belongs to — determines the completion behaviour
 * (mixdown surfaces a clip id; DAW downloads a ZIP bundle). */
type ExportKind = "mixdown" | "daw"

/** The export flow's state machine: idle → submitting → polling → success|error. */
export type StudioExportState =
  | { phase: "idle" }
  | { phase: "submitting" }
  | { phase: "polling"; progress?: string }
  // Mixdown carries the new clip id (for navigation / workspace refresh); DAW
  // reaches success after the ZIP download with a null id.
  | { phase: "success"; clipId: string | null }
  | { phase: "error"; message: string }

export type UseStudioExport = {
  state: StudioExportState
  /** Submit a mixdown and drive it to a single exported clip. */
  exportMixdown: (body: MixdownRequestBody, accessToken: string) => Promise<void>
  /** Submit a DAW export and download the resulting ZIP bundle on completion. */
  exportDaw: (body: StudioExportBody, accessToken: string) => Promise<void>
  /** Clear back to idle (dismiss an error / reset after success). */
  reset: () => void
}

/** Parse the download filename out of a Content-Disposition header, if present. */
function filenameFromDisposition(disposition: string | null): string | null {
  if (!disposition) return null
  const match = /filename="?([^"]+)"?/.exec(disposition)
  return match ? match[1] : null
}

/** Fetch the completed DAW bundle through the BFF and trigger a browser download. */
async function downloadDawBundle(
  jobId: string,
  accessToken: string
): Promise<boolean> {
  let blob: Blob
  let filename: string | null
  try {
    const res = await fetch(
      `/api/studio/export/daw/${encodeURIComponent(jobId)}`,
      { headers: { authorization: `Bearer ${accessToken}` } }
    )
    if (!res.ok) return false
    filename = filenameFromDisposition(res.headers.get("content-disposition"))
    blob = await res.blob()
  } catch {
    return false
  }

  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = filename ?? "studio-export.zip"
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
  return true
}

/**
 * Owns one studio export's lifecycle (US-19.6). After the 202 it polls the job
 * through the BFF proxy until completed/failed, exposing the backend's progress
 * string. A completed mixdown surfaces the new clip id (and fires
 * `onMixdownComplete` so the caller can refresh the workspace or navigate); a
 * completed DAW export downloads the ZIP bundle before reaching success.
 */
export function useStudioExport({
  onMixdownComplete,
}: { onMixdownComplete?: (clipId: string | null) => void } = {}): UseStudioExport {
  const router = useRouter()
  const [state, setState] = useState<StudioExportState>({ phase: "idle" })

  // The active job. A ref (not state) so the poll loop reads the latest without
  // re-subscribing; cleared the moment the job is superseded or terminal.
  const jobRef = useRef<{
    id: string
    token: string
    kind: ExportKind
    polls: number
  } | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Held in a ref so the poll loop's identity doesn't churn with the callback.
  const onCompleteRef = useRef(onMixdownComplete)
  useEffect(() => {
    onCompleteRef.current = onMixdownComplete
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

  // Clean up on unmount: clear the pending timer AND stop an in-flight poll
  // from rescheduling when its fetch resolves after cleanup (without the ref
  // guard the loop would keep polling until MAX_POLLS after navigation).
  const mountedRef = useRef(true)
  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      clearTimer()
    }
  }, [])

  const poll = useCallback(async () => {
    const job = jobRef.current
    if (!job) return
    const result = await fetchJobStatus(job.id, job.token)
    if (!mountedRef.current) return
    // A reset between the request and its response supersedes this job.
    if (jobRef.current?.id !== job.id) return

    switch (result.kind) {
      case "completed": {
        jobRef.current = null
        clearTimer()
        if (job.kind === "mixdown") {
          const clipId = result.clipIds[0] ?? null
          setState({ phase: "success", clipId })
          onCompleteRef.current?.(clipId)
          return
        }
        // DAW export: fetch + download the ZIP before declaring success.
        const ok = await downloadDawBundle(job.id, job.token)
        setState(
          ok
            ? { phase: "success", clipId: null }
            : { phase: "error", message: SUBMIT_FAILED }
        )
        return
      }
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
          setState({ phase: "error", message: "Export timed out. Please try again." })
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

  const run = useCallback(
    async (
      kind: ExportKind,
      endpoint: string,
      body: MixdownRequestBody | StudioExportBody,
      accessToken: string
    ) => {
      clearTimer()
      jobRef.current = null
      setState({ phase: "submitting" })

      let res: Response
      try {
        res = await fetch(endpoint, {
          method: "POST",
          headers: {
            authorization: `Bearer ${accessToken}`,
            "content-type": "application/json",
          },
          body: JSON.stringify(body),
        })
      } catch {
        setState({ phase: "error", message: SERVICE_DOWN })
        return
      }

      if (res.status === 401) {
        router.push("/login")
        return
      }
      if (!res.ok) {
        setState({ phase: "error", message: SUBMIT_FAILED })
        return
      }

      const data = (await res.json().catch(() => ({}))) as { job_id?: string }
      if (!data.job_id) {
        setState({ phase: "error", message: SUBMIT_FAILED })
        return
      }

      jobRef.current = { id: data.job_id, token: accessToken, kind, polls: 0 }
      setState({ phase: "polling" })
      // Poll immediately so a fast job doesn't sit idle for the first interval.
      void poll()
    },
    [poll, router]
  )

  const exportMixdown = useCallback(
    (body: MixdownRequestBody, accessToken: string) =>
      run("mixdown", "/api/studio/mixdown", body, accessToken),
    [run]
  )

  const exportDaw = useCallback(
    (body: StudioExportBody, accessToken: string) =>
      run("daw", "/api/studio/export/daw", body, accessToken),
    [run]
  )

  const reset = useCallback(() => {
    clearTimer()
    jobRef.current = null
    setState({ phase: "idle" })
  }, [])

  return { state, exportMixdown, exportDaw, reset }
}
