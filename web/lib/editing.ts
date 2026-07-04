/**
 * Typed client for the editing + iterative endpoints (US-17.3). Each modal
 * builds one of these request payloads and submits it through the same-origin
 * BFF proxy (`app/api/clips/[id]/*` and `app/api/mashup`), which forwards the
 * Bearer token to the backend. Every submit classifies the response into an
 * `EditSubmitResult` the modal's state machine switches on — mirroring
 * `lib/generate.ts`, plus the 402 (insufficient credits) case the paid
 * iterative endpoints can return.
 */

import type { BlendMode, SampleRole } from "@/lib/constants/editing"

// --- Request payloads (mirror the Pydantic models; optionals omitted when unset) ---

export type CropPayload = {
  start: string
  end: string
  fade_in?: string
  fade_out?: string
  snap_to_beat?: boolean
}

export type SpeedPayload = {
  multiplier?: number
  target_bpm?: number
  preserve_pitch?: boolean
}

export type RemasterPayload = {
  target_lufs?: number
}

export type ExtendPayload = {
  duration: string
  from_point?: string
  style_override?: string
  lyrics?: string
}

export type CoverPayload = {
  style: string
  lyrics_override?: string
}

export type RemixPayload = {
  style: string
}

export type RepaintPayload = {
  start: string
  end: string
  prompt: string
  style?: string
}

export type SamplePayload = {
  start: string
  end: string
  role: SampleRole
  prompt: string
  num_clips?: number
}

export type AddVocalPayload = {
  lyrics: string
  vocal_style?: string
}

export type MashupPayload = {
  clip_ids: string[]
  blend_mode?: BlendMode
  style?: string
}

/** One editing endpoint's accepted-job / error outcome, classified for the UI. */
export type EditSubmitResult =
  | { status: "accepted"; jobId: string; estimatedSeconds: number }
  | { status: "unauthorized" }
  | { status: "invalid"; detail: string }
  | { status: "insufficientCredits"; balance: number; required: number }
  | { status: "error"; detail: string }

/** Pull a human message out of a FastAPI error body (string or [{msg}] detail). */
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

/** Pull `{balance, required}` out of a 402 insufficient-credits detail object. */
function extractCredits(body: unknown): { balance: number; required: number } {
  const detail =
    body && typeof body === "object" && "detail" in body
      ? (body as { detail: unknown }).detail
      : undefined
  const obj = detail && typeof detail === "object" ? (detail as Record<string, unknown>) : {}
  const num = (v: unknown) => (typeof v === "number" ? v : 0)
  return { balance: num(obj.balance), required: num(obj.required) }
}

/**
 * POST a payload to a same-origin editing route and classify the response.
 * Shared by every submit function below; `path` is the BFF route (e.g.
 * `/api/clips/abc/crop`). Never throws — a network failure becomes an `error`
 * result so a modal never gets stuck mid-submit.
 */
async function postEdit(
  path: string,
  payload: unknown,
  accessToken: string
): Promise<EditSubmitResult> {
  let res: Response
  try {
    res = await fetch(path, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(payload),
    })
  } catch {
    return { status: "error", detail: "Something went wrong. Please try again." }
  }

  if (res.status === 202) {
    const body = await res.json().catch(() => ({}))
    const { job_id: jobId, estimated_time_seconds: estimated } = body as {
      job_id?: string
      estimated_time_seconds?: number
    }
    if (!jobId) {
      return { status: "error", detail: "Server returned an unexpected response." }
    }
    return {
      status: "accepted",
      jobId,
      estimatedSeconds: typeof estimated === "number" ? estimated : 0,
    }
  }
  if (res.status === 401) return { status: "unauthorized" }

  const body = await res.json().catch(() => ({}))
  if (res.status === 402) {
    return { status: "insufficientCredits", ...extractCredits(body) }
  }
  if (res.status === 422) {
    return { status: "invalid", detail: extractDetail(body, "Please check your input.") }
  }
  return {
    status: "error",
    detail: extractDetail(body, "Something went wrong. Please try again."),
  }
}

/** Strip `undefined`/empty-string optionals so the `extra="forbid"` backend is happy. */
function compact<T extends Record<string, unknown>>(payload: T): Partial<T> {
  const out: Record<string, unknown> = {}
  for (const [key, value] of Object.entries(payload)) {
    if (value === undefined) continue
    if (typeof value === "string" && value.trim() === "") continue
    out[key] = value
  }
  return out as Partial<T>
}

const clipPath = (clipId: string, op: string) =>
  `/api/clips/${encodeURIComponent(clipId)}/${op}`

// --- Editing endpoints (no credits) ---

export function submitCrop(clipId: string, payload: CropPayload, token: string) {
  return postEdit(clipPath(clipId, "crop"), compact(payload), token)
}

export function submitSpeed(clipId: string, payload: SpeedPayload, token: string) {
  return postEdit(clipPath(clipId, "speed"), compact(payload), token)
}

export function submitRemaster(clipId: string, payload: RemasterPayload, token: string) {
  return postEdit(clipPath(clipId, "remaster"), compact(payload), token)
}

// --- Iterative endpoints (consume credits) ---

export function submitExtend(clipId: string, payload: ExtendPayload, token: string) {
  return postEdit(clipPath(clipId, "extend"), compact(payload), token)
}

export function submitCover(clipId: string, payload: CoverPayload, token: string) {
  return postEdit(clipPath(clipId, "cover"), compact(payload), token)
}

export function submitRemix(clipId: string, payload: RemixPayload, token: string) {
  return postEdit(clipPath(clipId, "remix"), compact(payload), token)
}

export function submitRepaint(clipId: string, payload: RepaintPayload, token: string) {
  return postEdit(clipPath(clipId, "repaint"), compact(payload), token)
}

export function submitSample(clipId: string, payload: SamplePayload, token: string) {
  return postEdit(clipPath(clipId, "sample"), compact(payload), token)
}

export function submitAddVocal(clipId: string, payload: AddVocalPayload, token: string) {
  return postEdit(clipPath(clipId, "add-vocal"), compact(payload), token)
}

export function submitMashup(payload: MashupPayload, token: string) {
  return postEdit("/api/mashup", compact(payload), token)
}
