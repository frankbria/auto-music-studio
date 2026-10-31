// Short-form feed data (US-20.4): newest public clips from the discovery API
// (#651), paged by keyset cursor for infinite scroll.

import { clipAudioUrl } from "@/lib/clips"
import { fetchPublicClips } from "@/lib/discover"
import type { Clip } from "@/lib/workspace-clips"

export const FEED_PAGE_SIZE = 5

export type FeedItem = Clip & { audioUrl: string }

export type FeedPage = {
  items: FeedItem[]
  /** Cursor for the next page; null when the feed is exhausted. */
  nextCursor: string | null
}

export async function getFeedPage(cursor?: string | null): Promise<FeedPage> {
  const page = await fetchPublicClips({
    sort: "newest",
    limit: FEED_PAGE_SIZE,
    cursor,
  })
  return {
    items: page.clips.map((clip) => ({
      ...clip,
      audioUrl: clipAudioUrl(clip.id),
    })),
    nextCursor: page.nextCursor,
  }
}

/** Link that opens Create with this clip pre-attached as inspiration (US-20.3 seam). */
export function clipInspirationHref(item: FeedItem): string {
  const q = new URLSearchParams({
    inspiration: item.id,
    inspirationName: item.title ?? "Untitled clip",
  })
  return `/create?${q.toString()}`
}
