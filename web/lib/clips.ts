// Player track model + backend URL builders for clip media (US-15.6).
//
// The playbar plays `Track` objects that already carry their display metadata
// and a resolvable `audioUrl`. `clipAudioUrl` points at the same-origin stream
// proxy so an <audio src> resolves against this app rather than the (non-public)
// backend origin.
//
// ponytail: `clipArtworkUrl` still builds a bare /api/v1 backend path with no
// proxy route behind it, so cover art does not load. Left as-is — US-20.0 needs
// audio, and artwork wants its own proxy + placeholder story.

/** A single playable item in the player queue. */
export type Track = {
  id: string
  title: string
  /** Backend `ClipResponse` has no artist column yet; default to a placeholder. */
  artist: string
  /** Resolvable audio source for the <audio> element. */
  audioUrl: string
  /** Optional cover art; falls back to a music-note glyph when absent. */
  artworkUrl?: string
  /** Display duration in seconds; the real value is read off the audio element. */
  duration?: number
}

/** Build a playable Track from a clip (artist/artwork are placeholders today). */
export function trackFromClip(clip: {
  id: string
  title: string | null
  duration: number | null
}): Track {
  return {
    id: clip.id,
    title: clip.title ?? "Untitled clip",
    artist: "Unknown artist",
    audioUrl: clipAudioUrl(clip.id),
    artworkUrl: clipArtworkUrl(clip.id),
    duration: clip.duration ?? undefined,
  }
}

/**
 * Same-origin stream path for a clip's audio (US-20.0).
 *
 * Targets the `/stream` proxy, not `/audio`: this URL is consumed as an
 * `<audio src>`, which cannot attach a Bearer token. The proxy falls back to
 * the httpOnly `ams_access_token` cookie the browser sends automatically, so a
 * signed-in owner's *private* clip plays too (issue #282); public clips still
 * resolve anonymously. Seeking is supported. See the route's comment.
 */
export function clipAudioUrl(id: string): string {
  return `/api/clips/${encodeURIComponent(id)}/stream`
}

/** Backend cover-art path for a clip. */
export function clipArtworkUrl(id: string): string {
  return `/api/v1/clips/${encodeURIComponent(id)}/artwork`
}

/** Formats the same-origin audio proxy can convert to (US-17.2 downloads). */
export type DownloadFormat = "mp3" | "wav" | "flac"

/**
 * Download a clip's audio as a file via the same-origin proxy
 * (/api/clips/{id}/audio). Fetches with the in-memory Bearer token — a plain
 * <a href> can't attach one — then hands the bytes to the browser through a
 * temporary object-URL anchor. Returns false when the fetch fails so the
 * caller can surface an error state.
 */
export async function downloadClipAudio(
  id: string,
  format: DownloadFormat,
  accessToken: string,
  title: string | null
): Promise<boolean> {
  let blob: Blob
  try {
    const res = await fetch(
      `/api/clips/${encodeURIComponent(id)}/audio?format=${format}`,
      { headers: { authorization: `Bearer ${accessToken}` } }
    )
    if (!res.ok) return false
    blob = await res.blob()
  } catch {
    return false
  }

  const url = URL.createObjectURL(blob)
  try {
    const anchor = document.createElement("a")
    anchor.href = url
    anchor.download = `${title || id}.${format}`
    anchor.click()
  } finally {
    URL.revokeObjectURL(url)
  }
  return true
}

/** Outcome of a publish-toggle attempt (US-17.6). */
export type VisibilityResult =
  | { ok: true; isPublic: boolean }
  | { ok: false; guardFailed: boolean; message: string }

/**
 * Persist a clip's public/private state via `PATCH /api/clips/{id}` (US-17.6).
 * A 422 is the backend publish guard (missing title/style tags) — surfaced as
 * `guardFailed` so the caller can prompt for the missing fields instead of
 * showing a generic error. All other failures return `guardFailed: false`.
 */
export async function updateClipVisibility(
  id: string,
  isPublic: boolean,
  accessToken: string
): Promise<VisibilityResult> {
  let res: Response
  try {
    res = await fetch(`/api/clips/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: {
        authorization: `Bearer ${accessToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({ is_public: isPublic }),
    })
  } catch {
    return {
      ok: false,
      guardFailed: false,
      message: "Couldn't reach the server. Please try again.",
    }
  }
  if (res.ok) return { ok: true, isPublic }
  const detail = (await res.json().catch(() => ({}))) as { detail?: unknown }
  const message =
    typeof detail.detail === "string"
      ? detail.detail
      : "Couldn't update visibility. Please try again."
  return { ok: false, guardFailed: res.status === 422, message }
}

/** Format a number of seconds as `m:ss` (negative/NaN → `0:00`). */
export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
  const total = Math.floor(seconds)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}
