/**
 * Voice model API client (US-25.2 progress, US-25.3 library).
 *
 * Talks to the same-origin BFF proxies under `/api/voice-models`, which forward
 * the bearer token to the platform so the backend URL stays server-side.
 */

/** Where a training run has got to. */
export type VoiceTrainingStatus = {
  job_id: string
  voice_model_id: string
  status: "queued" | "training" | "ready" | "failed"
  phase: string
  /**
   * Percent complete, or **null** when the server cannot know it.
   *
   * ACE-Step reports steps and epochs rather than a fraction, so this is null
   * for runs where no total is available. Render "working" for null — do not
   * substitute 0, which reads as "stuck".
   */
  progress: number | null
  eta_seconds: number | null
  step: number | null
  epoch: number | null
  loss: number | null
  error: string | null
}

export type VoiceModelSummary = {
  id: string
  name: string
  description: string | null
  status: "queued" | "training" | "ready" | "failed"
  reference_count: number
  job_id: string | null
  error: string | null
  created_at: string
}

export class VoiceModelError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message)
    this.name = "VoiceModelError"
  }
}

async function parse<T>(res: Response, fallback: string): Promise<T> {
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new VoiceModelError(
      typeof body?.detail === "string" ? body.detail : fallback,
      res.status
    )
  }
  return body as T
}

/** Progress of one training run. Throws VoiceModelError with the status on failure. */
export async function fetchTrainingStatus(
  jobId: string,
  token: string
): Promise<VoiceTrainingStatus> {
  const res = await fetch(
    `/api/voice-models/train/${encodeURIComponent(jobId)}/status`,
    { headers: { authorization: `Bearer ${token}` }, cache: "no-store" }
  )
  return parse<VoiceTrainingStatus>(res, "Could not load training progress.")
}

/** Every voice model the caller owns, newest first. */
export async function fetchVoiceModels(token: string): Promise<VoiceModelSummary[]> {
  const res = await fetch("/api/voice-models", {
    headers: { authorization: `Bearer ${token}` },
    cache: "no-store",
  })
  return parse<VoiceModelSummary[]>(res, "Could not load your voice models.")
}

/** True once a run has stopped moving — polling should stop here. */
export function isSettled(status: VoiceTrainingStatus["status"]): boolean {
  return status === "ready" || status === "failed"
}

/** Human phase text. Falls back to the raw phase rather than inventing one. */
export function describePhase(status: VoiceTrainingStatus): string {
  if (status.status === "ready") return "Ready"
  if (status.status === "failed") return status.error ?? "Training failed"

  switch (status.phase) {
    case "preprocessing":
      return "Preparing your recordings"
    case "training":
      return "Training"
    case "finalizing":
      return "Finishing up"
    case "queued":
      return "Queued"
    default:
      return status.phase
  }
}
