// Client-side job-status polling for the creation flow (US-16.7). After a 202
// the form polls GET /api/jobs/{jobId} (the BFF proxy) until the job reaches a
// terminal state. The raw backend status is classified into a small result the
// poller switches on: keep-polling (pending/transient), done (completed/failed),
// or auth (redirect to login).

/** The backend job lifecycle states (mirrors api JobStatus). */
export type JobStatus = "queued" | "processing" | "completed" | "failed"

/** A single poll's outcome, classified for the generation state machine. */
export type JobPollResult =
  | { kind: "pending"; progress?: string }
  | { kind: "completed"; clipIds: string[] }
  | { kind: "failed"; error: string }
  | { kind: "unauthorized" }
  // Network blip / 5xx — not a real failure; the poller retries (up to its cap).
  | { kind: "transient" }

type JobStatusBody = {
  status?: JobStatus
  progress?: string
  clip_ids?: string[]
  error?: string
}

/** Poll one job's status through the BFF proxy and classify the response. */
export async function fetchJobStatus(
  jobId: string,
  accessToken: string
): Promise<JobPollResult> {
  let res: Response
  try {
    res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
  } catch {
    return { kind: "transient" }
  }

  if (res.status === 401) return { kind: "unauthorized" }
  // A 4xx other than 401 is terminal: the backend returns 404 for an unknown or
  // not-owned job, which polling can never recover from — fail fast instead of
  // spinning until the cap. 5xx and network errors stay transient (retried).
  if (res.status >= 400 && res.status < 500) {
    return { kind: "failed", error: "Generation failed. Please try again." }
  }
  if (!res.ok) return { kind: "transient" }

  const body = (await res.json().catch(() => ({}))) as JobStatusBody
  switch (body.status) {
    case "completed":
      return { kind: "completed", clipIds: body.clip_ids ?? [] }
    case "failed":
      return {
        kind: "failed",
        error: body.error || "Generation failed. Please try again.",
      }
    case "queued":
    case "processing":
      return { kind: "pending", progress: body.progress }
    default:
      // Unknown/missing status — treat as transient so a one-off odd body doesn't
      // abort an otherwise-healthy job.
      return { kind: "transient" }
  }
}
