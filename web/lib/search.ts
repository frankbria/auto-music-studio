// Search page data (US-20.2): full-text search and filters over public clips via
// the discovery API (#651), keyset-paged. The URL round-trips SearchParams.

import {
  fetchPublicClips,
  type DiscoverPage,
  type DiscoverSort,
} from "@/lib/discover"

export type SearchSort = DiscoverSort

export const SEARCH_SORTS: { value: SearchSort; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "newest", label: "Newest" },
]

const SORT_VALUES = new Set<SearchSort>(SEARCH_SORTS.map((s) => s.value))

/** The API rejects a longer query with a 422. */
const QUERY_MAX_LENGTH = 200

/** Search state; also the shape the URL round-trips to. */
export type SearchParams = {
  q: string
  /** Style/genre tag slug (matches Explore's `/search?style=` deep link). */
  style: string
  bpmMin: number | null
  bpmMax: number | null
  key: string
  model: string
  sort: SearchSort
}

export const DEFAULT_SEARCH: SearchParams = {
  q: "",
  style: "",
  bpmMin: null,
  bpmMax: null,
  key: "",
  model: "",
  sort: "relevance",
}

/** One page of public clips matching `params`; pass the previous page's cursor for the next. */
export function searchClips(
  params: SearchParams,
  cursor?: string | null,
  token?: string | null
): Promise<DiscoverPage> {
  return fetchPublicClips(
    {
      q: params.q.trim().slice(0, QUERY_MAX_LENGTH),
      style: params.style,
      bpm_min: params.bpmMin,
      bpm_max: params.bpmMax,
      key: params.key,
      model: params.model,
      sort: params.sort,
      cursor,
    },
    token
  )
}

/** A BPM from the URL; a negative one is dropped, since the API rejects it with a 422. */
function bpmOrNull(raw: string | null): number | null {
  if (raw == null) return null
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) && n >= 0 ? n : null
}

/** Read search state from a URL query string (invalid values fall to defaults). */
export function parseSearchParams(sp: URLSearchParams): SearchParams {
  const sortRaw = sp.get("sort") as SearchSort | null
  return {
    q: sp.get("q") ?? "",
    style: sp.get("style") ?? "",
    bpmMin: bpmOrNull(sp.get("bpm_min")),
    bpmMax: bpmOrNull(sp.get("bpm_max")),
    key: sp.get("key") ?? "",
    model: sp.get("model") ?? "",
    sort: sortRaw && SORT_VALUES.has(sortRaw) ? sortRaw : DEFAULT_SEARCH.sort,
  }
}

/** Serialize search state to a query string, omitting defaults for clean URLs. */
export function buildSearchQuery(params: SearchParams): string {
  const q = new URLSearchParams()
  if (params.q.trim()) q.set("q", params.q.trim())
  if (params.style) q.set("style", params.style)
  if (params.bpmMin != null) q.set("bpm_min", String(params.bpmMin))
  if (params.bpmMax != null) q.set("bpm_max", String(params.bpmMax))
  if (params.key) q.set("key", params.key)
  if (params.model) q.set("model", params.model)
  if (params.sort !== DEFAULT_SEARCH.sort) q.set("sort", params.sort)
  return q.toString()
}
