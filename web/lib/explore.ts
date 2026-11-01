// Explore page data (US-20.1): static genre channel tiles that link to Search,
// and New Releases, the newest public clips from the discovery API (#651).

import { fetchPublicClips } from "@/lib/discover"
import type { Clip } from "@/lib/workspace-clips"

/** A genre channel tile. Mirrors the eventual GET /genres shape. */
export type Genre = {
  id: string
  name: string
  slug: string
}

export const GENRES: Genre[] = [
  { id: "g-rock", name: "Rock", slug: "rock" },
  { id: "g-electronic", name: "Electronic", slug: "electronic" },
  { id: "g-hip-hop", name: "Hip Hop", slug: "hip-hop" },
  { id: "g-classical", name: "Classical", slug: "classical" },
  { id: "g-jazz", name: "Jazz", slug: "jazz" },
  { id: "g-pop", name: "Pop", slug: "pop" },
  // The style match anchors at symbol edges, so "r&b" finds "smooth r&b groove"; "rnb" found nothing (#657).
  { id: "g-rnb", name: "R&B", slug: "r&b" },
  { id: "g-country", name: "Country", slug: "country" },
]

/** Genre channel tiles. */
export function getGenreChannels(): Genre[] {
  return GENRES
}

export const NEW_RELEASES_LIMIT = 12

/** Newest public clips. */
export async function getNewReleases(token?: string | null): Promise<Clip[]> {
  const page = await fetchPublicClips(
    { sort: "newest", limit: NEW_RELEASES_LIMIT },
    token
  )
  return page.clips
}
