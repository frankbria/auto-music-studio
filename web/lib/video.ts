// Client-side video generation workflow (US-22.2). The video page submits a
// render job and polls its status — each call goes through a same-origin BFF
// proxy under `/api/videos/*` that forwards the Bearer token and keeps the
// backend URL server-side (mirrors lib/mastering). The backend endpoints
// (US-22.1) already exist.

/** The six style presets, mirroring the backend Literal. */
export type VideoStylePreset =
  | "abstract"
  | "cinematic"
  | "animated"
  | "lyric_video"
  | "live_performance"
  | "nature"

/** Output aspect ratios, mirroring the backend Literal. */
export type VideoAspectRatio = "16:9" | "9:16" | "1:1"

/** Output resolutions, mirroring the backend Literal. */
export type VideoResolution = "720p" | "1080p" | "4k"

/** Output frame rates, mirroring the backend Literal. */
export type VideoFrameRate = 24 | 30 | 60

/** Scene-transition modes, mirroring the backend Literal. */
export type VideoTransitions = "auto" | "cut" | "fade" | "dissolve"

/** The render lifecycle states the status endpoint reports. */
export type VideoState = "queued" | "rendering" | "encoding" | "complete" | "failed"

// Backend request bounds (src/acemusic/api/routers/videos.py).
export const MAX_REFERENCE_IMAGES = 5
export const PROMPT_MAX_LENGTH = 2000

/** A preset's display metadata plus the prompt text it seeds the textarea with. */
export type PresetOption = {
  value: VideoStylePreset
  label: string
  prompt: string
}

// Selecting a preset populates the style prompt with its seed text (US-22.2
// acceptance criterion) — the user can then edit it freely.
export const VIDEO_STYLE_PRESETS: PresetOption[] = [
  {
    value: "abstract",
    label: "Abstract",
    prompt: "Abstract flowing shapes and colors that pulse with the music's energy.",
  },
  {
    value: "cinematic",
    label: "Cinematic",
    prompt: "Cinematic film scenes with dramatic lighting and sweeping camera moves.",
  },
  {
    value: "animated",
    label: "Animated",
    prompt: "Vibrant animated illustration style with smooth, expressive motion.",
  },
  {
    value: "lyric_video",
    label: "Lyric Video",
    prompt: "Typography-driven lyric video with animated text as the visual focus.",
  },
  {
    value: "live_performance",
    label: "Live Performance",
    prompt: "Live concert performance footage with stage lighting and crowd energy.",
  },
  {
    value: "nature",
    label: "Nature",
    prompt: "Sweeping natural landscapes that mirror the mood of the song.",
  },
]

export const VIDEO_ASPECT_RATIOS: { value: VideoAspectRatio; label: string }[] = [
  { value: "16:9", label: "16:9 Landscape" },
  { value: "9:16", label: "9:16 Vertical" },
  { value: "1:1", label: "1:1 Square" },
]

/** A resolution's display metadata; Pro-only tiers are subscription-gated. */
export type ResolutionOption = {
  value: VideoResolution
  label: string
  proOnly: boolean
}

export const VIDEO_RESOLUTIONS: ResolutionOption[] = [
  { value: "720p", label: "720p", proOnly: false },
  { value: "1080p", label: "1080p", proOnly: true },
  { value: "4k", label: "4K", proOnly: true },
]

export const VIDEO_FRAME_RATES: { value: VideoFrameRate; label: string }[] = [
  { value: 24, label: "24 fps" },
  { value: 30, label: "30 fps" },
  { value: 60, label: "60 fps" },
]

export const VIDEO_TRANSITIONS: { value: VideoTransitions; label: string }[] = [
  { value: "auto", label: "Auto (AI-driven)" },
  { value: "cut", label: "Cut" },
  { value: "fade", label: "Fade" },
  { value: "dissolve", label: "Dissolve" },
]

/** Human label for a preset key, falling back to the raw value then a dash. */
export function presetLabel(value?: string): string {
  return VIDEO_STYLE_PRESETS.find((p) => p.value === value)?.label ?? value ?? "—"
}

// Client-side mirror of the server cost formula (src/acemusic/api/services/
// credits.py get_video_cost) for the pre-submit estimate — the server remains
// the billing authority. Same idiom as the MASTERING_SERVICES cost table.
const VIDEO_COSTS: Record<VideoResolution, number> = {
  "720p": 5,
  "1080p": 7,
  "4k": 8,
}
export const VIDEO_LONG_DURATION_S = 180
const VIDEO_LONG_DURATION_SURCHARGE = 2
const VIDEO_MAX_COST = 10

/** Estimated credit cost of one render (base by resolution, +2 past 3 min, cap 10). */
export function estimateVideoCost(
  resolution: VideoResolution,
  durationS: number | null
): number {
  let cost = VIDEO_COSTS[resolution]
  if (durationS !== null && durationS > VIDEO_LONG_DURATION_S) {
    cost += VIDEO_LONG_DURATION_SURCHARGE
  }
  return Math.min(cost, VIDEO_MAX_COST)
}

/** The render configuration a submission carries (clip id is passed separately). */
export type VideoConfig = {
  /** Free-form style description; required unless a preset is chosen. */
  prompt?: string
  style_preset?: VideoStylePreset
  /** Public http(s) URLs only — the backend rejects anything else. */
  reference_image_urls?: string[]
  lyrics_sync: boolean
  aspect_ratio: VideoAspectRatio
  resolution: VideoResolution
  frame_rate: VideoFrameRate
  transitions: VideoTransitions
}

/** A video job's live status as the backend reports it. */
export type VideoStatusDetail = {
  job_id: string
  status: VideoState
  progress: number
  eta_seconds?: number
  video_id?: string
  error?: string
  created_at?: string
  completed_at?: string
}

/** The outcome of submitting a video job, classified for the state machine. */
export type SubmitVideoResult =
  | { status: "accepted"; jobId: string }
  | { status: "unauthorized" }
  | { status: "insufficient_credits"; balance: number; required: number }
  | { status: "invalid"; detail: string }
  /** 503 — video generation isn't configured on this deployment. */
  | { status: "unavailable"; detail: string }
  | { status: "error"; detail: string }

/** A single status poll's outcome, classified for the job state machine. */
export type VideoPollResult =
  | { kind: "pending"; detail: VideoStatusDetail }
  | { kind: "complete"; detail: VideoStatusDetail }
  | { kind: "failed"; error: string }
  | { kind: "unauthorized" }
  // Network blip / 5xx — not a real failure; the poller retries (up to its cap).
  | { kind: "transient" }

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

/** Submit a video job through the BFF proxy and classify the response. */
export async function submitVideoJob(
  clipId: string,
  config: VideoConfig,
  accessToken: string
): Promise<SubmitVideoResult> {
  // Drop unset optional fields: the backend forbids unknown keys and treats
  // null prompt/preset as "neither provided", so absence is the safe encoding.
  const payload: Record<string, unknown> = { clip_id: clipId, ...config }
  for (const key of ["prompt", "style_preset", "reference_image_urls"] as const) {
    if (payload[key] === undefined) delete payload[key]
  }

  let res: Response
  try {
    res = await fetch("/api/videos/generate", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(payload),
    })
  } catch {
    return { status: "error", detail: "Video generation failed. Please try again." }
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
  if (res.status === 503) {
    return {
      status: "unavailable",
      detail: extractDetail(body, "Video generation is currently unavailable."),
    }
  }
  return {
    status: "error",
    detail: extractDetail(body, "Video generation failed. Please try again."),
  }
}

/** Poll one video job's status through the BFF proxy and classify it. */
export async function fetchVideoStatus(
  jobId: string,
  accessToken: string
): Promise<VideoPollResult> {
  let res: Response
  try {
    res = await fetch(`/api/videos/${encodeURIComponent(jobId)}/status`, {
      headers: { authorization: `Bearer ${accessToken}` },
    })
  } catch {
    return { kind: "transient" }
  }

  if (res.status === 401) return { kind: "unauthorized" }
  // A 4xx other than 401 is terminal (404 = unknown/not-owned job) — polling
  // can never recover, so fail fast. 5xx/network stay transient (retried).
  if (res.status >= 400 && res.status < 500) {
    return { kind: "failed", error: "Video generation failed. Please try again." }
  }
  if (!res.ok) return { kind: "transient" }

  const detail = (await res.json().catch(() => ({}))) as VideoStatusDetail
  switch (detail.status) {
    case "complete":
      return { kind: "complete", detail }
    case "failed":
      return {
        kind: "failed",
        error: detail.error || "Video generation failed. Please try again.",
      }
    case "queued":
    case "rendering":
    case "encoding":
      return { kind: "pending", detail }
    default:
      // Unknown/missing status — transient so one odd body doesn't abort a job.
      return { kind: "transient" }
  }
}
