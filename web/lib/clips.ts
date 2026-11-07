// Player track model + backend URL builders for clip media (US-15.6).
//
// The playbar plays `Track` objects that already carry their display metadata
// and a resolvable `audioUrl`. `clipAudioUrl` points at the same-origin stream
// proxy so an <audio src> resolves against this app rather than the (non-public)
// backend origin; `clipArtworkUrl` does the same for an <img src> (#737).

import type { Visibility } from "@/lib/workspace-clips"

/** A single playable item in the player queue. */
export type Track = {
  id: string
  title: string
  /** The clip owner's public name; a placeholder when they set none. */
  artist: string
  /** Resolvable audio source for the <audio> element. */
  audioUrl: string
  /** Optional cover art; falls back to a music-note glyph when absent. */
  artworkUrl?: string
  /** Display duration in seconds; the real value is read off the audio element. */
  duration?: number
}

/** Build a playable Track from a clip (artwork is a placeholder today). */
export function trackFromClip(clip: {
  id: string
  title: string | null
  duration: number | null
  artist?: string | null
}): Track {
  return {
    id: clip.id,
    title: clip.title ?? "Untitled clip",
    artist: clip.artist || "Unknown artist",
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

/**
 * Same-origin cover-art path for a clip (#737). Like `clipAudioUrl`, the proxy
 * falls back to the access cookie so an <img> can show a private clip's art.
 * A clip with no art 404s, and the player shows its music-note placeholder.
 */
export function clipArtworkUrl(id: string): string {
  return `/api/clips/${encodeURIComponent(id)}/artwork`
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

/** Outcome of a visibility-change attempt (US-17.6 / tri-state in US-20.7). */
export type VisibilityResult =
  | { ok: true; visibility: Visibility }
  | { ok: false; guardFailed: boolean; message: string }

/**
 * Persist a clip's visibility via `PATCH /api/clips/{id}` (US-17.6, extended
 * to the tri-state Private/Unlisted/Public in US-20.7). A 422 is the backend
 * publish guard (missing title/style tags, only reachable going "public") —
 * surfaced as `guardFailed` so the caller can prompt for the missing fields
 * instead of showing a generic error. All other failures return
 * `guardFailed: false`.
 */
export async function updateClipVisibility(
  id: string,
  visibility: Visibility,
  accessToken: string
): Promise<VisibilityResult> {
  const result = await patchClip(
    id,
    { visibility },
    accessToken,
    "Couldn't update visibility. Please try again."
  )
  return result.ok
    ? { ok: true, visibility }
    : { ok: false, guardFailed: result.status === 422, message: result.message }
}

/**
 * Rename a clip via `PATCH /api/clips/{id}` (#736). The server screens the title,
 * so a refusal's message is its string `detail` when it sends one.
 */
export async function updateClipTitle(
  id: string,
  title: string,
  accessToken: string
) {
  return patchClip(
    id,
    { title },
    accessToken,
    "Couldn't rename this song. Please try again."
  )
}

/** PATCH the clip proxy; a failure carries the server's string `detail`, else `fallback`. */
async function patchClip(
  id: string,
  body: Record<string, unknown>,
  accessToken: string,
  fallback: string
): Promise<
  { ok: true } | { ok: false; status: number | null; message: string }
> {
  let res: Response
  try {
    res = await fetch(`/api/clips/${encodeURIComponent(id)}`, {
      method: "PATCH",
      headers: {
        authorization: `Bearer ${accessToken}`,
        "content-type": "application/json",
      },
      body: JSON.stringify(body),
    })
  } catch {
    return {
      ok: false,
      status: null,
      message: "Couldn't reach the server. Please try again.",
    }
  }
  if (res.ok) return { ok: true }
  const detail = (await res.json().catch(() => ({}))) as { detail?: unknown }
  const message = typeof detail.detail === "string" ? detail.detail : fallback
  return { ok: false, status: res.status, message }
}

/** Format a number of seconds as `m:ss` (negative/NaN → `0:00`). */
export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
  const total = Math.floor(seconds)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}
