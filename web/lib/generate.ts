// Client-side generation submission for the Simple creation form (US-16.1).
// The form state is turned into the backend's GenerationRequest payload and
// POSTed through the same-origin BFF proxy (app/api/generate/route.ts), which
// forwards the Bearer token and keeps the backend URL server-side. Progress and
// result handling are deferred to US-16.7 — here we just enqueue and report the
// accepted job id (or the failure) back to the form.

/** The slice of form state needed to build a generation request. */
export type GenerationFormData = {
  description: string
  lyrics: string
  instrumental: boolean
  selectedTags: string[]
}

/** Subset of the backend GenerationRequest this form sends (extra keys forbidden). */
export type GenerationPayload = {
  prompt: string
  style?: string
  lyrics?: string
  instrumental: boolean
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
  const style = data.selectedTags.join(", ").trim()

  const payload: GenerationPayload = {
    prompt: description || lyrics,
    instrumental: data.instrumental,
  }
  if (style) payload.style = style
  if (lyrics) payload.lyrics = lyrics
  return payload
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

/** Submit a generation request through the BFF proxy and classify the response. */
export async function submitGeneration(
  data: GenerationFormData,
  accessToken: string
): Promise<SubmitResult> {
  const res = await fetch("/api/generate", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${accessToken}`,
    },
    body: JSON.stringify(buildGenerationPayload(data)),
  })

  if (res.status === 202) {
    const body = await res.json().catch(() => ({}))
    return { status: "accepted", jobId: (body as { job_id?: string }).job_id ?? "" }
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
