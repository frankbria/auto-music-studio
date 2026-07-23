// Client-side mastering workflow (US-21.2). The mastering tab submits a job,
// polls its status, lists the mastered previews, and approves one — each call
// goes through a same-origin BFF proxy under `/api/mastering/*` that forwards
// the Bearer token and keeps the backend URL server-side (mirrors lib/generate
// + lib/job-status). The backend endpoints (US-12.1/12.4) already exist.

/** The five mastering profiles (loudness targets), mirroring the backend Literal. */
export type MasteringProfile =
  | "streaming"
  | "soundcloud"
  | "club"
  | "vinyl"
  | "custom"

/** The mastering service backends, mirroring the backend Literal. */
export type MasteringService = "dolby" | "landr" | "bakuage"

/** Output container, mirroring the backend Literal. */
export type MasteringFormat = "wav" | "mp3" | "flac"

/** The backend job lifecycle states (mirrors api JobStatus). */
export type MasteringStatus = "queued" | "processing" | "completed" | "failed"

/** A profile's display metadata. `lufs` is null for custom (user-specified). */
export type ProfileOption = {
  value: MasteringProfile
  label: string
  lufs: number | null
}

/** A service's display metadata (`cost` is the credit price per master). */
export type ServiceOption = {
  value: MasteringService
  label: string
  cost: number
}

// Fixed loudness targets per profile (src/acemusic/api/services/mastering.py
// PROFILE_LUFS_MAP). Custom reveals a user LUFS input constrained to the API's
// remaster bounds.
export const MASTERING_PROFILES: ProfileOption[] = [
  { value: "streaming", label: "Streaming", lufs: -14 },
  { value: "soundcloud", label: "SoundCloud", lufs: -12 },
  { value: "club", label: "Club / DJ", lufs: -6 },
  { value: "vinyl", label: "Vinyl", lufs: -18 },
  { value: "custom", label: "Custom", lufs: null },
]

// Per-service credit cost (src/acemusic/api/services/credits.py). dolby is the
// backend default.
export const MASTERING_SERVICES: ServiceOption[] = [
  { value: "dolby", label: "Dolby.io", cost: 3 },
  { value: "landr", label: "LANDR", cost: 2 },
  { value: "bakuage", label: "Bakuage", cost: 5 },
]

// Custom LUFS bounds — the backend rejects anything outside this range (422).
export const CUSTOM_LUFS_MIN = -70
export const CUSTOM_LUFS_MAX = -5

/** The mastering configuration a submission carries (clip id is passed separately). */
export type MasteringConfig = {
  profile: MasteringProfile
  service: MasteringService
  format: MasteringFormat
  /** Required for the custom profile, forbidden otherwise (backend-validated). */
  target_lufs?: number
}

/** A mastering job's status + (once complete) its master + metrics. */
export type MasteringJobDetail = {
  job_id: string
  status: MasteringStatus
  source_clip_id?: string
  profile?: string
  service?: string
  target_lufs?: number
  created_at?: string
  completed_at?: string
  mastered_clip_id?: string
  metrics?: MasteringMetrics
  error?: string
}

/** Backend mastering metrics. All fields optional — services return partial sets. */
export type MasteringMetrics = {
  loudness?: number
  /** Per-band EQ gains (Dolby returns 16 bands); shape is service-dependent. */
  eq_bands?: number[]
  /** Stereo image width/balance (Dolby); absent for loudness-only services. */
  stereo_width?: number
  stereo_balance?: number
}

/** One mastered candidate for A/B comparison against the original. */
export type PreviewItem = {
  preview_id: string
  audio_url: string
  profile?: string
  service?: string
  metrics?: MasteringMetrics
  /** Mastered-minus-original integrated loudness (dB); null when unavailable. */
  loudness_delta?: number | null
}

/** The A/B comparison set: original audio/metrics plus every mastered candidate. */
export type PreviewsResponse = {
  source_clip_id?: string
  original_audio_url?: string
  original_metrics?: MasteringMetrics
  previews: PreviewItem[]
}

/** The outcome of submitting a mastering job, classified for the state machine. */
export type SubmitMasteringResult =
  | { status: "accepted"; jobId: string }
  | { status: "unauthorized" }
  | { status: "insufficient_credits"; balance: number; required: number }
  | { status: "invalid"; detail: string }
  | { status: "error"; detail: string }

/** A single status poll's outcome, classified for the job state machine. */
export type MasteringPollResult =
  | { kind: "pending"; detail: MasteringJobDetail }
  | { kind: "completed"; detail: MasteringJobDetail }
  | { kind: "failed"; error: string }
  | { kind: "unauthorized" }
  // Network blip / 5xx — not a real failure; the poller retries (up to its cap).
  | { kind: "transient" }

/** The outcome of approving a preview, classified for the approval flow. */
export type ApproveResult =
  | { status: "approved"; clipId: string; audioUrl: string }
  | { status: "unauthorized" }
  | { status: "error"; detail: string }

/** Pull a human-readable message out of a FastAPI error body (string or 422 list). */
function extractDetail(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail
    if (typeof detail === "string") return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0]
      if (first && typeof first === "object" && "msg" in first) {
        return String((first as { msg: unknown }).msg)
      }
    }
  }
  return fallback
}

/** Submit a mastering job through the BFF proxy and classify the response. */
export async function submitMasteringJob(
  clipId: string,
  config: MasteringConfig,
  accessToken: string
): Promise<SubmitMasteringResult> {
  let res: Response
  try {
    res = await fetch("/api/mastering/jobs", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ clip_id: clipId, ...config }),
    })
  } catch {
    return { status: "error", detail: "Mastering failed. Please try again." }
  }

  if (res.status === 202) {
    const body = (await res.json().catch(() => ({}))) as { job_id?: string }
    if (!body.job_id) {
      return { status: "error", detail: "Server returned an unexpected response." }
    }
    return { status: "accepted", jobId: body.job_id }
  }
  if (res.status === 401) return { status: "unauthorized" }

  const body = await res.json().catch(() => ({}))
  if (res.status === 402) {
    // The 402 detail is an object {error, balance, required}.
    const detail = (body as { detail?: { balance?: number; required?: number } })
      .detail
    return {
      status: "insufficient_credits",
      balance: detail?.balance ?? 0,
      required: detail?.required ?? 0,
    }
  }
  if (res.status === 422) {
    return { status: "invalid", detail: extractDetail(body, "Please check your input.") }
  }
  return {
    status: "error",
    detail: extractDetail(body, "Mastering failed. Please try again."),
  }
}

/** Poll one mastering job's status through the BFF proxy and classify it. */
export async function fetchMasteringStatus(
  jobId: string,
  accessToken: string
): Promise<MasteringPollResult> {
  let res: Response
  try {
    res = await fetch(`/api/mastering/jobs/${encodeURIComponent(jobId)}`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
  } catch {
    return { kind: "transient" }
  }

  if (res.status === 401) return { kind: "unauthorized" }
  // A 4xx other than 401 is terminal (404 = unknown/not-owned job) — polling
  // can never recover, so fail fast. 5xx/network stay transient (retried).
  if (res.status >= 400 && res.status < 500) {
    return { kind: "failed", error: "Mastering failed. Please try again." }
  }
  if (!res.ok) return { kind: "transient" }

  const detail = (await res.json().catch(() => ({}))) as MasteringJobDetail
  switch (detail.status) {
    case "completed":
      return { kind: "completed", detail }
    case "failed":
      return { kind: "failed", error: detail.error || "Mastering failed. Please try again." }
    case "queued":
    case "processing":
      return { kind: "pending", detail }
    default:
      // Unknown/missing status — transient so one odd body doesn't abort a job.
      return { kind: "transient" }
  }
}

/** Fetch the A/B preview set for a completed job. Null on error/unauthorized. */
export async function fetchMasteringPreviews(
  jobId: string,
  accessToken: string
): Promise<PreviewsResponse | null> {
  let res: Response
  try {
    res = await fetch(`/api/mastering/jobs/${encodeURIComponent(jobId)}/previews`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
  } catch {
    return null
  }
  if (!res.ok) return null
  return (await res.json().catch(() => null)) as PreviewsResponse | null
}

/** Approve (promote) a preview to the final master through the BFF proxy. */
export async function approveMasteringPreview(
  jobId: string,
  previewId: string,
  accessToken: string
): Promise<ApproveResult> {
  let res: Response
  try {
    res = await fetch(`/api/mastering/jobs/${encodeURIComponent(jobId)}/approve`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify({ preview_id: previewId }),
    })
  } catch {
    return { status: "error", detail: "Approval failed. Please try again." }
  }
  if (res.status === 401) return { status: "unauthorized" }
  const body = await res.json().catch(() => ({}))
  if (!res.ok) {
    return { status: "error", detail: extractDetail(body, "Approval failed. Please try again.") }
  }
  const { clip_id: clipId, audio_url: audioUrl } = body as {
    clip_id?: string
    audio_url?: string
  }
  if (!clipId) {
    return { status: "error", detail: "Server returned an unexpected response." }
  }
  return { status: "approved", clipId, audioUrl: audioUrl ?? "" }
}
