// Types + client helpers for the workspace clip-library panel (US-16.5).
//
// Mirrors the backend ClipResponse/WorkspaceResponse shapes
// (src/acemusic/api/routers/clips.py, workspaces.py). Search, sort, and
// pagination are server-driven; the Liked/Public/Uploads filters are applied
// client-side (see applyClientFilters) because the backend GET /clips endpoint
// has no query params for them yet.

export type SortOrder = "newest" | "oldest"

/** A clip as returned by GET /api/v1/clips (ClipResponse). No `updated_at`. */
export type Clip = {
  id: string
  workspace_id: string
  title: string | null
  format: string | null
  duration: number | null
  bpm: number | null
  key: string | null
  style_tags: string[]
  lyrics: string | null
  vocal_language: string | null
  model: string | null
  seed: number | null
  inference_steps: number | null
  parent_clip_ids: string[]
  generation_mode: string | null
  is_public: boolean
  created_at: string
}

/** A workspace as returned by GET /api/v1/workspaces (WorkspaceResponse). */
export type Workspace = {
  id: string
  name: string
  clip_count: number
  is_default: boolean
  created_at: string
  updated_at: string | null
}

export type ClipListResponse = {
  clips: Clip[]
  total: number
  page: number
  per_page: number
  total_pages: number
}

export type WorkspaceListResponse = {
  workspaces: Workspace[]
  total: number
}

/** The three filter toggles in the panel header. */
export type ClipFilters = {
  liked: boolean
  public: boolean
  uploads: boolean
}

export const EMPTY_FILTERS: ClipFilters = {
  liked: false,
  public: false,
  uploads: false,
}

/** Server-supported query parameters for GET /api/clips. */
export type ClipSearchParams = {
  workspace_id?: string
  search?: string
  sort?: SortOrder
  page?: number
  per_page?: number
}

/** Build the query string for GET /api/clips from server-supported params. */
export function buildClipQuery(params: ClipSearchParams): string {
  const q = new URLSearchParams()
  if (params.workspace_id) q.set("workspace_id", params.workspace_id)
  const search = params.search?.trim()
  if (search) q.set("search", search)
  if (params.sort) q.set("sort", params.sort)
  if (params.page) q.set("page", String(params.page))
  if (params.per_page) q.set("per_page", String(params.per_page))
  return q.toString()
}

/** Number of active filter toggles, for the Filters button badge. */
export function activeFilterCount(filters: ClipFilters): number {
  return (
    Number(filters.liked) + Number(filters.public) + Number(filters.uploads)
  )
}

/**
 * Apply the Liked/Public/Uploads toggles client-side.
 *
 * ponytail: backend GET /clips has no liked/public/uploads params, so these
 * narrow the *fetched page* in the browser — server-side filtering is a backend
 * follow-up. `liked` is sourced from the player's localStorage-backed likedIds
 * set (the only place "liked" exists today). Enabled toggles are AND-combined.
 */
export function applyClientFilters(
  clips: Clip[],
  filters: ClipFilters,
  likedIds: readonly string[]
): Clip[] {
  const liked = new Set(likedIds)
  return clips.filter((c) => {
    if (filters.liked && !liked.has(c.id)) return false
    if (filters.public && !c.is_public) return false
    if (filters.uploads && c.generation_mode !== "upload") return false
    return true
  })
}
