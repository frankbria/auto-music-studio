// Client reads of the public discovery API (#651) through the same-origin BFF
// (app/api/discover). Feed, Explore and Search all page through these.

import type { Clip } from "@/lib/workspace-clips"

export type DiscoverSort = "newest" | "relevance"

/** Query for GET /api/v1/discover/clips; empty and null fields are left out. */
export type DiscoverQuery = {
  q?: string
  style?: string
  bpm_min?: number | null
  bpm_max?: number | null
  key?: string
  model?: string
  sort?: DiscoverSort
  limit?: number
  cursor?: string | null
}

export type DiscoverPage = {
  clips: Clip[]
  /** Opaque keyset cursor for the next page; null on the last page. */
  nextCursor: string | null
  total: number
}

export type DiscoverFacets = { keys: string[]; models: string[] }

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { accept: "application/json" } })
  if (!res.ok) throw new Error(`Discovery request failed (${res.status})`)
  return (await res.json()) as T
}

export async function fetchPublicClips(
  query: DiscoverQuery
): Promise<DiscoverPage> {
  const search = new URLSearchParams()
  for (const [name, value] of Object.entries(query)) {
    if (value != null && value !== "") search.set(name, String(value))
  }
  const qs = search.toString()
  const body = await getJson<{
    clips: Clip[]
    next_cursor: string | null
    total: number
  }>(`/api/discover/clips${qs ? `?${qs}` : ""}`)
  return { clips: body.clips, nextCursor: body.next_cursor, total: body.total }
}

export function fetchFacets(): Promise<DiscoverFacets> {
  return getJson<DiscoverFacets>("/api/discover/facets")
}
