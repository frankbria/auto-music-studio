// Search page data seam (US-20.2).
//
// The Search page searches/filters/sorts clips client-side over the same mock
// discovery pool as Explore (US-20.1). There is no public discovery *search*
// endpoint yet: the backend `GET /clips` list is auth-gated and owner-scoped, so
// it can't serve an anonymous listener searching across all public music. When a
// public search endpoint lands, swap `searchClips`' body for a fetch — the page
// consumes these functions, not the pool.
//
// ponytail: all matching/sorting is in-memory over ~12 clips, so no debounce or
// indexing here — that lives in the backend once search moves server-side.

import { getAllClips } from "@/lib/explore"
import type { Clip } from "@/lib/workspace-clips"

export type SearchSort = "relevance" | "newest" | "popular"

export const SEARCH_SORTS: { value: SearchSort; label: string }[] = [
  { value: "relevance", label: "Relevance" },
  { value: "newest", label: "Newest" },
  { value: "popular", label: "Most Popular" },
]

const SORT_VALUES = new Set<SearchSort>(SEARCH_SORTS.map((s) => s.value))

/** Server-independent search state; also the shape the URL round-trips to. */
export type SearchParams = {
  q: string
  /** Style/genre tag slug (matches Explore's `/search?style=` deep link). */
  style: string
  bpmMin: number | null
  bpmMax: number | null
  key: string
  model: string
  sort: SearchSort
  page: number
}

export const DEFAULT_SEARCH: SearchParams = {
  q: "",
  style: "",
  bpmMin: null,
  bpmMax: null,
  key: "",
  model: "",
  sort: "relevance",
  page: 1,
}

/** Results per page for the client-side pagination of the mock pool. */
export const PER_PAGE = 8

const has = (haystack: string | null, needle: string) =>
  (haystack ?? "").toLowerCase().includes(needle)

/** Match a clip against the free-text query (title, tags, lyrics). */
function matchesQuery(clip: Clip, needle: string): boolean {
  if (!needle) return true
  return (
    has(clip.title, needle) ||
    has(clip.style_tags.join(" "), needle) ||
    has(clip.lyrics, needle)
  )
}

/** Higher = a better free-text match, for relevance sorting. */
function relevanceScore(clip: Clip, needle: string): number {
  if (!needle) return 0
  const title = (clip.title ?? "").toLowerCase()
  let score = 0
  if (title.includes(needle)) score += title.startsWith(needle) ? 5 : 3
  if (clip.style_tags.some((t) => t.toLowerCase().includes(needle))) score += 2
  if (has(clip.lyrics, needle)) score += 1
  return score
}

/**
 * Filter + sort the discovery pool for the given search state (no pagination —
 * that's `paginate`). Pass `clips` to search a set other than the default pool
 * (tests). Filters are AND-combined; an empty/`null` field means "any".
 */
export function searchClips(
  params: SearchParams,
  clips: Clip[] = getAllClips()
): Clip[] {
  const needle = params.q.trim().toLowerCase()
  const style = params.style.trim().toLowerCase()

  const filtered = clips.filter((c) => {
    if (!matchesQuery(c, needle)) return false
    if (style && !c.style_tags.some((t) => t.toLowerCase() === style)) return false
    if (params.bpmMin != null && (c.bpm == null || c.bpm < params.bpmMin)) return false
    if (params.bpmMax != null && (c.bpm == null || c.bpm > params.bpmMax)) return false
    if (params.key && c.key !== params.key) return false
    if (params.model && c.model !== params.model) return false
    return true
  })

  const newest = (a: Clip, b: Clip) =>
    Date.parse(b.created_at) - Date.parse(a.created_at)
  const popular = (a: Clip, b: Clip) =>
    (b.play_count ?? 0) - (a.play_count ?? 0)

  if (params.sort === "newest") return filtered.sort(newest)
  if (params.sort === "popular") return filtered.sort(popular)
  // Relevance: rank by match score when there's a query, else fall back to
  // newest so the default browse view still has a sensible order.
  if (!needle) return filtered.sort(newest)
  return filtered.sort(
    (a, b) =>
      relevanceScore(b, needle) - relevanceScore(a, needle) || popular(a, b)
  )
}

export type SearchPage = {
  clips: Clip[]
  page: number
  total: number
  totalPages: number
}

/** Slice filtered results to a page. Clamps `page` into `[1, totalPages]`. */
export function paginate(clips: Clip[], page: number): SearchPage {
  const total = clips.length
  const totalPages = Math.max(1, Math.ceil(total / PER_PAGE))
  const clamped = Math.min(Math.max(1, page), totalPages)
  const start = (clamped - 1) * PER_PAGE
  return {
    clips: clips.slice(start, start + PER_PAGE),
    page: clamped,
    total,
    totalPages,
  }
}

function intOrNull(raw: string | null): number | null {
  if (raw == null) return null
  const n = Number.parseInt(raw, 10)
  return Number.isFinite(n) ? n : null
}

/** Read search state from a URL query string (invalid values fall to defaults). */
export function parseSearchParams(sp: URLSearchParams): SearchParams {
  const sortRaw = sp.get("sort") as SearchSort | null
  const page = intOrNull(sp.get("page"))
  return {
    q: sp.get("q") ?? "",
    style: sp.get("style") ?? "",
    bpmMin: intOrNull(sp.get("bpm_min")),
    bpmMax: intOrNull(sp.get("bpm_max")),
    key: sp.get("key") ?? "",
    model: sp.get("model") ?? "",
    sort: sortRaw && SORT_VALUES.has(sortRaw) ? sortRaw : DEFAULT_SEARCH.sort,
    page: page != null && page > 0 ? page : 1,
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
  if (params.page > 1) q.set("page", String(params.page))
  return q.toString()
}

/** Distinct musical keys present in the pool, for the key filter options. */
export function availableKeys(clips: Clip[] = getAllClips()): string[] {
  return [...new Set(clips.map((c) => c.key).filter((k): k is string => !!k))].sort()
}

/** Distinct model ids present in the pool, for the model filter options. */
export function availableModels(clips: Clip[] = getAllClips()): string[] {
  return [...new Set(clips.map((c) => c.model).filter((m): m is string => !!m))].sort()
}
