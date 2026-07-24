// Release listing + distribution-status seam (US-21.6).
//
// The backend release API is fully built (US-13.x): `GET /releases` lists a
// user's releases with per-channel `channel_statuses`, and `/status`,
// `/prepare`, `/submit` round it out. But the web app has no release-creation
// flow yet — the Distribute tab only persists a localStorage draft
// ([[us-21-4-distribution-metadata-form]]) — so `GET /releases` returns an empty
// list for every web user today, and the dashboard would have nothing to show.
//
// So, like mastering history ([[us-21-3-mastering-status-tracking]]) and the
// Stage-20 pages, this is a typed seam seeded across every status state. Its
// shape mirrors the backend `ReleaseListResponse` / `ReleaseResponse` /
// `channel_statuses` so it swaps cleanly: when web release-creation lands, replace
// `fetchReleases`'s body with a BFF fetch to `GET /releases` (mirroring
// lib/distribution's SoundCloud proxy) and the hook + components stay unchanged.
//
// Two forward-compat fields the backend Release model does NOT carry yet live on
// the per-channel status here: `permalink` (the live external URL, e.g.
// SoundCloud's `permalink_url`) and `rejectionReason`. They are the minimal
// backend additions US-21.6 implies; the UI reads them now so the wiring is ready.

/** Per-channel distribution lifecycle — matches backend DistributionStatus
 *  (`draft → ready → submitted → in_review → live | rejected`). */
export type DistributionStatus =
  | "draft"
  | "ready"
  | "submitted"
  | "in_review"
  | "live"
  | "rejected"

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

/** The live external link for a channel, or null when it isn't live / has no URL. */
export function externalLink(channel: ChannelDistribution): string | null {
  return channel.status === "live" && channel.permalink ? channel.permalink : null
}

const HOUR = 60 * 60 * 1000

function hoursAgo(h: number): string {
  return new Date(Date.now() - h * HOUR).toISOString()
}

// Seed — one release per DistributionStatus so the dashboard demonstrates every
// badge, plus a live-with-permalink row (external link AC) and a
// rejected-with-reason row (rejection AC). clipId uses real Explore-pool ids
// (clip-*) so a ReleaseCard's "song" link resolves like everywhere else.
const SEED: ReleaseSummary[] = [
  {
    id: "rel-live-1",
    clipId: "clip-neon",
    title: "Neon Skyline",
    artist: "Ivory Lanes",
    genre: "Synthwave",
    releaseDate: "2026-06-01",
    isrc: "US-AMS-26-00012",
    upc: "0885686000121",
    createdAt: hoursAgo(2),
    channels: [
      {
        channel: "soundcloud",
        status: "live",
        permalink: "https://soundcloud.com/ivory-lanes/neon-skyline",
      },
    ],
  },
  {
    id: "rel-review-1",
    clipId: "clip-crown",
    title: "Crownfall",
    artist: "Ivory Lanes",
    genre: "Drum & Bass",
    releaseDate: "2026-06-10",
    isrc: "US-AMS-26-00019",
    upc: "0885686000190",
    createdAt: hoursAgo(20),
    channels: [
      { channel: "distrokid", status: "in_review" },
      { channel: "soundcloud", status: "live", permalink: "https://soundcloud.com/ivory-lanes/crownfall" },
    ],
  },
  {
    id: "rel-submitted-1",
    clipId: "clip-gold",
    title: "Gold Rush 88",
    artist: "Ivory Lanes",
    genre: "House",
    releaseDate: "2026-06-14",
    isrc: "US-AMS-26-00021",
    upc: "0885686000213",
    createdAt: hoursAgo(30),
    channels: [{ channel: "landr", status: "submitted" }],
  },
  {
    id: "rel-rejected-1",
    clipId: "clip-paper",
    title: "Paper Lanterns",
    artist: "Ivory Lanes",
    genre: "Ambient",
    releaseDate: "2026-05-28",
    isrc: "US-AMS-26-00007",
    upc: "0885686000077",
    createdAt: hoursAgo(50),
    channels: [
      {
        channel: "distrokid",
        status: "rejected",
        rejectionReason: "Cover art is below the 3000×3000px minimum.",
      },
    ],
  },
  {
    id: "rel-ready-1",
    clipId: "clip-velvet",
    title: "Velvet Static",
    artist: "Ivory Lanes",
    genre: "Downtempo",
    releaseDate: "2026-06-20",
    isrc: "US-AMS-26-00025",
    upc: "0885686000251",
    createdAt: hoursAgo(70),
    channels: [{ channel: "soundcloud", status: "ready" }],
  },
  {
    id: "rel-draft-1",
    clipId: "clip-mid",
    title: "Midnight Payload",
    artist: "Ivory Lanes",
    genre: "Techno",
    releaseDate: "2026-07-01",
    createdAt: hoursAgo(96),
    channels: [{ channel: "soundcloud", status: "draft" }],
  },
]

/**
 * Fetch the user's releases, newest first (AC: dashboard shows all releases).
 *
 * Async on purpose so the polling hook is real transport: swap this body for a
 * BFF fetch to `GET /releases` when web release-creation lands, mapping
 * `channel_statuses` → `channels`. Callers won't change. Returns a fresh copy so
 * a consumer can't mutate the seed.
 */
export async function fetchReleases(): Promise<ReleaseSummary[]> {
  return SEED.map((r) => ({ ...r, channels: r.channels.map((c) => ({ ...c })) })).sort(
    (a, b) => b.createdAt.localeCompare(a.createdAt)
  )
}
