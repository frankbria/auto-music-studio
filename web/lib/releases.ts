// Release listing + distribution status for the dashboard (US-21.6, #748).
//
// Reads the caller's releases from the backend `GET /api/v1/releases` through the `/api/releases` BFF and maps
// `channel_statuses` to `channels`, with each channel's public link and rejection reason (#758) where known.

/** Per-channel distribution lifecycle — matches backend DistributionStatus
 *  (`draft → ready → submitted → in_review → live | rejected`). */
export type DistributionStatus =
  "draft" | "ready" | "submitted" | "in_review" | "live" | "rejected"

/** One channel's status for a release (mirrors backend ChannelStatus, plus the
 *  two forward-compat fields the backend must add: external link + reason). */
export type ChannelDistribution = {
  /** Channel id: "soundcloud", "landr", "distrokid", "tunecore", … */
  channel: string
  status: DistributionStatus
  /** Live external URL, present when `status === "live"` (else null). */
  permalink?: string | null
  /** Why the platform rejected it, present when `status === "rejected"` (else null). */
  rejectionReason?: string | null
}

/** A release summary row for the dashboard (mirrors backend ReleaseResponse). */
export type ReleaseSummary = {
  id: string
  clipId: string
  title: string
  artist: string
  genre: string
  /** ISO date. */
  releaseDate: string
  album?: string | null
  isrc?: string | null
  upc?: string | null
  /** Per-channel status across every engaged channel. */
  channels: ChannelDistribution[]
  /** ISO timestamp; drives newest-first ordering. */
  createdAt: string
}

/** Human label for a channel id (falls back to a Title-cased id). */
export function channelLabel(channel: string): string {
  const known: Record<string, string> = {
    soundcloud: "SoundCloud",
    landr: "LANDR",
    distrokid: "DistroKid",
    tunecore: "TuneCore",
  }
  return known[channel] ?? channel.charAt(0).toUpperCase() + channel.slice(1)
}

/** The live external link for a channel, or null when it isn't live / has no URL.
 *  `permalink` is backend/external-sourced and rendered as an `<a href>`, so only
 *  an absolute http(s) URL is allowed through — a `javascript:`/`data:` scheme
 *  would be an XSS sink (mirrors the repo's other URL-sink guards). */
export function externalLink(channel: ChannelDistribution): string | null {
  if (channel.status !== "live" || !channel.permalink) return null
  try {
    const { protocol } = new URL(channel.permalink)
    return protocol === "http:" || protocol === "https:"
      ? channel.permalink
      : null
  } catch {
    return null
  }
}

/** One release as the backend lists it (the fields the dashboard reads). */
type ApiRelease = {
  id: string
  clip_id: string
  title: string
  artist: string
  genre: string
  release_date: string
  album_name: string | null
  isrc: string | null
  upc: string | null
  created_at: string
  channel_statuses: Record<string, DistributionStatus>
  channel_permalinks: Record<string, string>
  channel_rejection_reasons: Record<string, string>
}

function toSummary(release: ApiRelease): ReleaseSummary {
  return {
    id: release.id,
    clipId: release.clip_id,
    title: release.title,
    artist: release.artist,
    genre: release.genre,
    releaseDate: release.release_date,
    album: release.album_name,
    isrc: release.isrc,
    upc: release.upc,
    createdAt: release.created_at,
    channels: Object.entries(release.channel_statuses).map(
      ([channel, status]) => ({
        channel,
        status,
        permalink: release.channel_permalinks[channel] ?? null,
        rejectionReason: release.channel_rejection_reasons[channel] ?? null,
      })
    ),
  }
}

/** The caller's releases, newest first. Throws when the list can't be read, so the dashboard shows its error. */
export async function fetchReleases(
  accessToken: string
): Promise<ReleaseSummary[]> {
  const res = await fetch("/api/releases", {
    headers: { authorization: `Bearer ${accessToken}` },
  })
  if (!res.ok) throw new Error(`Releases request failed (${res.status}).`)
  const body: { releases: ApiRelease[] } = await res.json()
  return body.releases
    .map(toSummary)
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
}
