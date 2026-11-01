// Playlist data seam (US-20.3).
//
// Playlists have no backend yet: the UI runs on a local, typed client store whose
// shapes mirror the eventual `/playlists` API. Songs are public clips picked from
// discovery (#654). Mutations here are PURE — each returns a new Playlist — so the
// client store (contexts/playlists-context) can hold them in React state; swap
// these bodies for fetch()es when the API lands and callers won't change.
//
// ponytail: in-memory only, session-scoped — no localStorage/persistence (YAGNI until
// there's a real backend to sync with). Custom covers are object URLs, so they also
// live only for the session.

import type { Clip } from "@/lib/workspace-clips"

export type PlaylistVisibility = "private" | "public"

/** A playlist. `clipIds` is the ordered song list; `coverDataUrl` null → auto mosaic. */
export type Playlist = {
  id: string
  name: string
  description: string | null
  visibility: PlaylistVisibility
  clipIds: string[]
  coverDataUrl: string | null
  createdAt: string
}

function newId(): string {
  // crypto.randomUUID exists in browsers and the jsdom/node test env.
  return `pl-${crypto.randomUUID()}`
}

function now(): string {
  return new Date().toISOString()
}

/** The session starts with no playlists; replace with `GET /playlists` when it lands. */
export function initialPlaylists(): Playlist[] {
  return []
}

/** A fresh, empty, private playlist. */
export function createPlaylist(name: string, description = ""): Playlist {
  return {
    id: newId(),
    name: name.trim(),
    description: description.trim() || null,
    visibility: "private",
    clipIds: [],
    coverDataUrl: null,
    createdAt: now(),
  }
}

/** Rename / re-describe a playlist (empty description → null). */
export function renamePlaylist(
  pl: Playlist,
  name: string,
  description = ""
): Playlist {
  return { ...pl, name: name.trim(), description: description.trim() || null }
}

export function setVisibility(
  pl: Playlist,
  visibility: PlaylistVisibility
): Playlist {
  return { ...pl, visibility }
}

/** Append a song, ignoring duplicates (a playlist holds each song once). */
export function addClip(pl: Playlist, clipId: string): Playlist {
  if (pl.clipIds.includes(clipId)) return pl
  return { ...pl, clipIds: [...pl.clipIds, clipId] }
}

export function removeClip(pl: Playlist, clipId: string): Playlist {
  return { ...pl, clipIds: pl.clipIds.filter((id) => id !== clipId) }
}

/**
 * Move the song at `from` to `to` (drag-to-reorder / up-down buttons). Out-of-range
 * indices are a no-op, so callers don't have to bounds-check the drag target.
 */
export function reorderClips(pl: Playlist, from: number, to: number): Playlist {
  const n = pl.clipIds.length
  if (from < 0 || from >= n || to < 0 || to >= n || from === to) return pl
  const next = [...pl.clipIds]
  const [moved] = next.splice(from, 1)
  next.splice(to, 0, moved)
  return { ...pl, clipIds: next }
}

/** Set (or clear, with null) a custom cover image. Clearing falls back to the mosaic. */
export function setCover(pl: Playlist, coverDataUrl: string | null): Playlist {
  return { ...pl, coverDataUrl }
}

/** Resolve `clipIds` to Clips in playlist order, dropping ids not in `known`. */
export function playlistClips(
  pl: Playlist,
  known: ReadonlyMap<string, Clip>
): Clip[] {
  return pl.clipIds
    .map((id) => known.get(id))
    .filter((c): c is Clip => c != null)
}

/** Public share URL for a playlist. `origin` comes from the caller (window.location). */
export function buildShareUrl(origin: string, id: string): string {
  return `${origin}/playlists/${id}`
}

/**
 * Link that opens the Create page with this playlist as generation context
 * (AC: "Use as Inspiration"). The create page reads these params and seeds the
 * inspiration chip.
 */
export function buildInspirationHref(pl: Playlist): string {
  const q = new URLSearchParams({
    inspiration: pl.id,
    inspirationName: pl.name,
  })
  return `/create?${q.toString()}`
}
