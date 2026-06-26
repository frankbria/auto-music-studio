// Client-side generation submission for the Simple creation form (US-16.1).
// The form state is turned into the backend's GenerationRequest payload and
// POSTed through the same-origin BFF proxy (app/api/generate/route.ts), which
// forwards the Bearer token and keeps the backend URL server-side. Progress and
// result handling are deferred to US-16.7 — here we just enqueue and report the
// accepted job id (or the failure) back to the form.

import {
  BPM_MAX,
  BPM_MIN,
  DURATION_MAX,
  DURATION_MIN,
  KEY_MAX_LENGTH,
  LYRICS_MAX_LENGTH,
  PROMPT_MAX_LENGTH,
  STYLE_INFLUENCE_MAX,
  STYLE_INFLUENCE_MIN,
  STYLE_MAX_LENGTH,
  WEIRDNESS_MAX,
  WEIRDNESS_MIN,
} from "@/lib/constants/generation"

/** The slice of form state needed to build a generation request. */
export type GenerationFormData = {
  description: string
  lyrics: string
  instrumental: boolean
  selectedTags: string[]
}

/** Subset of the backend GenerationRequest these forms send (extra keys forbidden). */
export type GenerationPayload = {
  prompt: string
  style?: string
  lyrics?: string
  instrumental: boolean
  vocal_language?: string
  bpm?: number | "auto"
  key?: string
  time_signature?: string
  duration?: number
  weirdness?: number
  style_influence?: number
  seed?: number
}

export type SubmitResult =
  | { status: "accepted"; jobId: string }
  | { status: "unauthorized" }
  | { status: "invalid"; detail: string }
  | { status: "error"; detail: string }

/**
 * Build the backend payload from form state. The backend requires a non-empty
 * `prompt` and forbids unknown keys, so empty optionals are omitted and the
 * prompt falls back to the lyrics when no description is given — the Create
 * button enables on either field, and this keeps that lyrics-only path valid.
 */
export function buildGenerationPayload(
  data: GenerationFormData
): GenerationPayload {
  const description = data.description.trim()
  const lyrics = data.lyrics.trim()
  const style = data.selectedTags.join(", ")

  const payload: GenerationPayload = {
    prompt: description || lyrics,
    instrumental: data.instrumental,
  }
  if (style) payload.style = style
  if (lyrics) payload.lyrics = lyrics
  return payload
}

/** Form state for the Advanced creation form (US-16.2). */
export type AdvancedFormData = {
  lyrics: string
  /** "auto" lets the model write lyrics — user-entered lyrics are not sent. */
  lyricsMode: "manual" | "auto"
  vocalLanguage: string
  /** Free-text, comma-separated styles. Combined with `selectedTags`. */
  styles: string
  selectedTags: string[]
  instrumental: boolean
  bpmAuto: boolean
  /** Raw numeric-input string; "" means unset. */
  bpm: string
  key: string
  timeSignature: string
  duration: string
  weirdness: number
  styleInfluence: number
  /** "Random" → no explicit seed is sent (the job picks one). */
  seedRandom: boolean
  seed: string
}

/** Combine the styles textarea and the selected tag pills into one style string. */
export function combineStyles(styles: string, tags: string[]): string {
  return [styles.trim(), ...tags].filter(Boolean).join(", ")
}

/**
 * Build the backend payload from the Advanced form. There is no description
 * field in Advanced mode, so the combined style string is the prompt (falling
 * back to the lyrics). The lyrics fallback is capped to PROMPT_MAX_LENGTH — the
 * backend allows longer lyrics than prompts, so an uncapped fallback would 422
 * on lyrics-only submissions; the full lyrics still go in the `lyrics` field.
 * UI-only fields (vocal gender, exclude styles, song title, workspace) are never
 * included — the backend uses `extra="forbid"`.
 */
export function buildAdvancedPayload(data: AdvancedFormData): GenerationPayload {
  const style = combineStyles(data.styles, data.selectedTags)
  const lyrics = data.lyricsMode === "manual" ? data.lyrics.trim() : ""

  const payload: GenerationPayload = {
    prompt: (style || lyrics).slice(0, PROMPT_MAX_LENGTH),
    instrumental: data.instrumental,
    weirdness: data.weirdness,
    style_influence: data.styleInfluence,
  }
  if (style) payload.style = style
  if (lyrics) payload.lyrics = lyrics
  if (data.vocalLanguage) payload.vocal_language = data.vocalLanguage
  // Auto = no tempo preference, so omit bpm entirely (matching every other
  // optional field) rather than pinning "auto" — the backend's model_dump uses
  // exclude_none, so an absent bpm and an explicit "auto" are NOT equivalent.
  if (!data.bpmAuto && data.bpm.trim()) payload.bpm = Number(data.bpm)
  if (data.key) payload.key = data.key
  if (data.timeSignature) payload.time_signature = data.timeSignature
  if (data.duration.trim()) payload.duration = Number(data.duration)
  if (!data.seedRandom && data.seed.trim()) payload.seed = Number(data.seed)
  return payload
}

/**
 * Validate the Advanced form against the backend's ranges before submitting, so
 * a bad value surfaces inline instead of as a 422. Returns the first problem
 * message, or null when the form is valid.
 */
export function validateAdvanced(data: AdvancedFormData): string | null {
  const style = combineStyles(data.styles, data.selectedTags)
  const lyrics = data.lyricsMode === "manual" ? data.lyrics.trim() : ""
  if (!style && !lyrics) return "Add a style or lyrics to create."

  if (style.length > STYLE_MAX_LENGTH) {
    return `Styles must be ${STYLE_MAX_LENGTH} characters or fewer.`
  }
  if (lyrics.length > LYRICS_MAX_LENGTH) {
    return `Lyrics must be ${LYRICS_MAX_LENGTH} characters or fewer.`
  }
  if (!data.bpmAuto && data.bpm.trim()) {
    const bpm = Number(data.bpm)
    if (!Number.isFinite(bpm) || bpm < BPM_MIN || bpm > BPM_MAX) {
      return `BPM must be between ${BPM_MIN} and ${BPM_MAX}.`
    }
  }
  if (data.duration.trim()) {
    const duration = Number(data.duration)
    if (!Number.isFinite(duration) || duration < DURATION_MIN || duration > DURATION_MAX) {
      return `Duration must be between ${DURATION_MIN} and ${DURATION_MAX} seconds.`
    }
  }
  if (data.key.length > KEY_MAX_LENGTH) {
    return `Key must be ${KEY_MAX_LENGTH} characters or fewer.`
  }
  if (data.weirdness < WEIRDNESS_MIN || data.weirdness > WEIRDNESS_MAX) {
    return `Weirdness must be between ${WEIRDNESS_MIN} and ${WEIRDNESS_MAX}.`
  }
  if (data.styleInfluence < STYLE_INFLUENCE_MIN || data.styleInfluence > STYLE_INFLUENCE_MAX) {
    return `Style influence must be between ${STYLE_INFLUENCE_MIN} and ${STYLE_INFLUENCE_MAX}.`
  }
  return null
}

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

/** Submit the Simple creation form through the BFF proxy. */
export function submitGeneration(
  data: GenerationFormData,
  accessToken: string
): Promise<SubmitResult> {
  return postGeneration(buildGenerationPayload(data), accessToken)
}

/** Submit the Advanced creation form through the BFF proxy. */
export function submitAdvancedGeneration(
  data: AdvancedFormData,
  accessToken: string
): Promise<SubmitResult> {
  return postGeneration(buildAdvancedPayload(data), accessToken)
}

/** POST a built payload through the BFF proxy and classify the response. */
async function postGeneration(
  payload: GenerationPayload,
  accessToken: string
): Promise<SubmitResult> {
  let res: Response
  try {
    res = await fetch("/api/generate", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        authorization: `Bearer ${accessToken}`,
      },
      body: JSON.stringify(payload),
    })
  } catch {
    // Network failure / aborted request — never let it bubble out and leave the
    // form stuck on "Creating..."; surface it as a generic error instead.
    return { status: "error", detail: "Generation failed. Please try again." }
  }

  if (res.status === 202) {
    const body = await res.json().catch(() => ({}))
    const jobId = (body as { job_id?: string }).job_id
    // A 202 with no usable job id is unexpected (non-JSON body, schema drift) —
    // treat it as an error rather than report a hollow success US-16.7 can't poll.
    if (!jobId) {
      return { status: "error", detail: "Server returned an unexpected response." }
    }
    return { status: "accepted", jobId }
  }
  if (res.status === 401) return { status: "unauthorized" }

  const body = await res.json().catch(() => ({}))
  if (res.status === 422) {
    return { status: "invalid", detail: extractDetail(body, "Please check your input.") }
  }
  return {
    status: "error",
    detail: extractDetail(body, "Generation failed. Please try again."),
  }
}
