// Short-form feed data seam (US-20.4).
//
// Like Explore (US-20.1) and Search (US-20.2), the feed has no backend: it runs on
// the same local mock pool. This module composes a discovery "mix" and paginates it
// for infinite scroll. Swap `getFeedPage`'s body for a cursor fetch when a
// `GET /feed` endpoint exists; the FeedView consumes the getter, not the pool.
//
// ponytail: the pool is ~12 clips, so infinite scroll cycles it with a per-page
// render key rather than fetching more — real audio + a real feed replace both the
// shared sample URL and the cycling. Nothing here is load-bearing beyond the demo.

import { getNewReleases, getStaffPicks, getTrendingClips } from "@/lib/explore"
import type { Clip } from "@/lib/workspace-clips"

/** Every feed item plays this shared sample — the mock pool has no per-clip audio.
 *  Swap for `streamUrl(clip.id)` once discovery serves real streams. */
export const FEED_AUDIO_URL = "/demo/sample.wav"

export const FEED_PAGE_SIZE = 5

/** Cap so infinite scroll terminates (the pool is finite); real feeds page forever. */
export const FEED_MAX_PAGES = 5

/** Mock artist names — clips carry no artist field, so one is assigned per clip. */
const ARTISTS = [
  "Nova Reverie",
  "The Glass Hours",
  "Kairo",
  "Velvet Circuit",
  "Lucid Ffield",
  "Mono Mirage",
  "Saffron Kites",
  "Echo & Ember",
]

/** Stable string hash → index; keeps artist assignment deterministic per clip id. */
function hashIndex(id: string, mod: number): number {
  let h = 0
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0
  return h % mod
}

/** Deterministic mock artist for a clip. */
export function artistForClip(id: string): string {
  return ARTISTS[hashIndex(id, ARTISTS.length)]
}

/**
 * A feed item: a Clip plus display extras. `id` stays the real clip id (likes,
 * share, remix, and links all key on it); `key` is a per-page-unique render key so
 * a cycled pool doesn't produce duplicate React keys.
 */
export type FeedItem = Clip & {
  artist: string
  audioUrl: string
  key: string
}

/**
 * The feed "algorithm": interleave trending, new releases, and staff picks, then
 * dedupe by id (first occurrence wins). Followed-artist content isn't modeled yet
 * (no follow graph), so staff picks stand in for personalized recommendations.
 */
function baseFeed(): Clip[] {
  const trending = getTrendingClips("7d")
  const fresh = getNewReleases()
  const picks = getStaffPicks()

  const ordered: Clip[] = []
  const seen = new Set<string>()
  // Round-robin the three sources so the feed doesn't front-load one bucket.
  const sources = [trending, fresh, picks]
  const maxLen = Math.max(...sources.map((s) => s.length))
  for (let i = 0; i < maxLen; i++) {
    for (const source of sources) {
      const clip = source[i]
      if (clip && !seen.has(clip.id)) {
        seen.add(clip.id)
        ordered.push(clip)
      }
    }
  }
  return ordered
}

function toFeedItem(clip: Clip, page: number, index: number): FeedItem {
  return {
    ...clip,
    artist: artistForClip(clip.id),
    audioUrl: FEED_AUDIO_URL,
    key: `${clip.id}--p${page}#${index}`,
  }
}

export type FeedPage = {
  items: FeedItem[]
  page: number
  hasMore: boolean
}

/**
 * One page of the feed (1-based). The base mix is cycled so pages past the pool's
 * length keep returning items (infinite scroll) with unique render keys, up to
 * `FEED_MAX_PAGES`.
 */
export function getFeedPage(page: number): FeedPage {
  const base = baseFeed()
  const clamped = Math.min(Math.max(1, Math.trunc(page)), FEED_MAX_PAGES)
  const start = (clamped - 1) * FEED_PAGE_SIZE
  const items = Array.from({ length: FEED_PAGE_SIZE }, (_, i) => {
    const clip = base[(start + i) % base.length]
    return toFeedItem(clip, clamped, i)
  })
  return { items, page: clamped, hasMore: clamped < FEED_MAX_PAGES }
}

/** Link that opens Create with this clip pre-attached as inspiration (US-20.3 seam). */
export function clipInspirationHref(item: FeedItem): string {
  const q = new URLSearchParams({
    inspiration: item.id,
    inspirationName: item.title ?? "Untitled clip",
  })
  return `/create?${q.toString()}`
}
