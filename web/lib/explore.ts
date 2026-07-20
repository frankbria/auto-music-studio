// Explore page mock data service (US-20.1).
//
// The Explore page (trending, genre channels, staff picks, new releases, charts)
// has no backend: only a single-clip public read exists (/api/clips/{id}/public),
// and the list endpoint is owner-scoped. So the five sections read from this
// local, typed mock layer whose shapes mirror the eventual public discovery API
// (Clip + engagement counters). When those endpoints land, swap each getter's
// body for a fetch and delete the pool — the components consume these functions,
// not the data.
//
// ponytail: no artificial network delay / IntersectionObserver lazy-load here —
// the reads are synchronous local data, so there is nothing to defer. Add both
// when a getter becomes a real network fetch.

import type { Clip } from "@/lib/workspace-clips"

/** A genre channel tile. Mirrors the eventual GET /genres shape. */
export type Genre = {
  id: string
  name: string
  slug: string
}

export type TrendingRange = "24h" | "7d"
export type ChartMetric = "plays" | "likes" | "shares"

/** Chart metric → the Clip engagement field it ranks by. */
const METRIC_FIELD: Record<ChartMetric, "play_count" | "like_count" | "share_count"> = {
  plays: "play_count",
  likes: "like_count",
  shares: "share_count",
}

export const GENRES: Genre[] = [
  { id: "g-rock", name: "Rock", slug: "rock" },
  { id: "g-electronic", name: "Electronic", slug: "electronic" },
  { id: "g-hip-hop", name: "Hip Hop", slug: "hip-hop" },
  { id: "g-classical", name: "Classical", slug: "classical" },
  { id: "g-jazz", name: "Jazz", slug: "jazz" },
  { id: "g-pop", name: "Pop", slug: "pop" },
  { id: "g-rnb", name: "R&B", slug: "rnb" },
  { id: "g-country", name: "Country", slug: "country" },
]

/** Build a mock discovery clip; only discovery-relevant fields are meaningful. */
function mockClip(
  id: string,
  title: string,
  style_tags: string[],
  created_at: string,
  engagement: { plays: number; likes: number; shares: number },
  extra: Partial<Clip> = {}
): Clip {
  return {
    id,
    workspace_id: null,
    title,
    format: "wav",
    duration: 90 + (engagement.plays % 120),
    bpm: 100 + (engagement.likes % 60),
    key: null,
    style_tags,
    lyrics: null,
    vocal_language: null,
    model: "ace-step-v1",
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: "generate",
    is_public: true,
    created_at,
    is_owner: false,
    play_count: engagement.plays,
    like_count: engagement.likes,
    share_count: engagement.shares,
    ...extra,
  }
}

// Varied pool: titles, styles, ages, and engagement all differ so trending and
// charts produce distinct orderings (and so the 24h vs 7d toggle visibly moves).
const POOL: Clip[] = [
  mockClip("clip-neon", "Neon Skyline", ["synthwave", "electronic"], "2026-07-19T09:00:00Z", { plays: 8200, likes: 640, shares: 210 }),
  mockClip("clip-velvet", "Velvet Static", ["lofi", "chill"], "2026-07-19T06:30:00Z", { plays: 5400, likes: 980, shares: 90 }),
  mockClip("clip-emberr", "Ember Roads", ["rock", "indie"], "2026-07-18T22:10:00Z", { plays: 12100, likes: 720, shares: 340 }),
  mockClip("clip-glass", "Glass Cathedral", ["classical", "ambient"], "2026-07-18T14:00:00Z", { plays: 3100, likes: 410, shares: 620 }),
  mockClip("clip-gold", "Gold Rush 88", ["hip-hop", "trap"], "2026-07-17T20:45:00Z", { plays: 15800, likes: 1240, shares: 470 }),
  mockClip("clip-tide", "Tidal Bloom", ["pop", "dance"], "2026-07-17T11:20:00Z", { plays: 9700, likes: 1580, shares: 260 }),
  mockClip("clip-brass", "Midnight Brass", ["jazz", "soul"], "2026-07-16T19:05:00Z", { plays: 2600, likes: 300, shares: 55 }),
  mockClip("clip-dust", "Dust & Denim", ["country", "folk"], "2026-07-15T08:15:00Z", { plays: 4300, likes: 520, shares: 130 }),
  mockClip("clip-mono", "Monochrome Heart", ["rnb", "soul"], "2026-07-14T17:40:00Z", { plays: 7100, likes: 890, shares: 175 }),
  mockClip("clip-pulse", "Pulse Theory", ["electronic", "techno"], "2026-07-13T05:00:00Z", { plays: 11200, likes: 610, shares: 400 }),
  mockClip("clip-paper", "Paper Lanterns", ["lofi", "ambient"], "2026-07-12T12:30:00Z", { plays: 1900, likes: 260, shares: 40 }),
  mockClip("clip-crown", "Crownfall", ["rock", "metal"], "2026-07-11T21:55:00Z", { plays: 6800, likes: 700, shares: 220 }),
]

/**
 * Trending clips for a time range. 24h weights recent virality (likes + shares);
 * 7d weights sustained plays — so the two ranges surface a different lead clip.
 */
export function getTrendingClips(range: TrendingRange): Clip[] {
  const score =
    range === "24h"
      ? (c: Clip) => (c.like_count ?? 0) + (c.share_count ?? 0)
      : (c: Clip) => c.play_count ?? 0
  return [...POOL].sort((a, b) => score(b) - score(a)).slice(0, 8)
}

/** Genre channel tiles. */
export function getGenreChannels(): Genre[] {
  return GENRES
}

/** Editorially curated highlights (a fixed hand-picked subset). */
export function getStaffPicks(): Clip[] {
  const picks = ["clip-glass", "clip-velvet", "clip-brass", "clip-mono", "clip-paper"]
  return picks.map((id) => POOL.find((c) => c.id === id)!).filter(Boolean)
}

/** Recently published clips, newest first. */
export function getNewReleases(): Clip[] {
  return [...POOL].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)
  )
}

/** Top clips ranked by the chosen engagement metric, highest first. */
export function getCharts(metric: ChartMetric = "plays"): Clip[] {
  const field = METRIC_FIELD[metric]
  return [...POOL]
    .sort((a, b) => (b[field] ?? 0) - (a[field] ?? 0))
    .slice(0, 10)
}
