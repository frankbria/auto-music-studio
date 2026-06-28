// Player track model + backend URL builders for clip media (US-15.6).
//
// The playbar plays `Track` objects that already carry their display metadata
// and a resolvable `audioUrl`. The `clipAudioUrl`/`clipArtworkUrl` helpers
// build the backend paths (GET /api/v1/clips/{id}/audio | /artwork) so that, as
// soon as a clip-browsing UI lands, it can turn a clip id into a playable
// Track. Those backend endpoints are owner-scoped/public on the FastAPI side;
// wiring the same-origin proxy + auth for streaming is a later story.

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

/** Backend audio stream path for a clip. */
export function clipAudioUrl(id: string): string {
  return `/api/v1/clips/${encodeURIComponent(id)}/audio`
}

/** Backend cover-art path for a clip. */
export function clipArtworkUrl(id: string): string {
  return `/api/v1/clips/${encodeURIComponent(id)}/artwork`
}

/** Format a number of seconds as `m:ss` (negative/NaN → `0:00`). */
export function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
  const total = Math.floor(seconds)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${s.toString().padStart(2, "0")}`
}
