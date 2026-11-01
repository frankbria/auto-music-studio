"use client"

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react"

import {
  addClip as addClipTo,
  createPlaylist,
  initialPlaylists,
  removeClip as removeClipFrom,
  renamePlaylist,
  reorderClips as reorderClipsIn,
  setCover as setCoverOn,
  setVisibility as setVisibilityOn,
  type Playlist,
  type PlaylistVisibility,
} from "@/lib/playlists"
import type { Clip } from "@/lib/workspace-clips"

// In-memory playlist store (US-20.3). Lives in the /playlists layout so the list
// page and the detail page share one reactive source — plain component state would
// reset on navigation between them. Each action applies the matching pure helper
// from lib/playlists to the one playlist it targets, replacing it immutably so
// consumers re-render. Playlists hold clip ids, so the store also remembers each
// clip added this session (`clipsById`) to render them without refetching. Swap
// the initial state + actions for API calls when the /playlists backend exists.

type PlaylistsContextValue = {
  playlists: Playlist[]
  /** Every clip added to a playlist this session, for `playlistClips`. */
  clipsById: ReadonlyMap<string, Clip>
  getPlaylist: (id: string) => Playlist | undefined
  create: (name: string, description?: string) => Playlist
  rename: (id: string, name: string, description?: string) => void
  remove: (id: string) => void
  setVisibility: (id: string, visibility: PlaylistVisibility) => void
  addClip: (id: string, clip: Clip) => void
  removeClip: (id: string, clipId: string) => void
  reorderClips: (id: string, from: number, to: number) => void
  setCover: (id: string, coverDataUrl: string | null) => void
}

const PlaylistsContext = createContext<PlaylistsContextValue | null>(null)

export function PlaylistsProvider({ children }: { children: React.ReactNode }) {
  const [playlists, setPlaylists] = useState<Playlist[]>(initialPlaylists)
  const [clipsById, setClipsById] = useState<ReadonlyMap<string, Clip>>(
    () => new Map()
  )

  /** Replace the playlist with matching id by running `fn` over it. */
  const patch = useCallback(
    (id: string, fn: (pl: Playlist) => Playlist) =>
      setPlaylists((list) => list.map((pl) => (pl.id === id ? fn(pl) : pl))),
    []
  )

  const create = useCallback((name: string, description = "") => {
    const pl = createPlaylist(name, description)
    setPlaylists((list) => [pl, ...list])
    return pl
  }, [])

  const value = useMemo<PlaylistsContextValue>(
    () => ({
      playlists,
      clipsById,
      getPlaylist: (id) => playlists.find((pl) => pl.id === id),
      create,
      rename: (id, name, description) =>
        patch(id, (pl) => renamePlaylist(pl, name, description)),
      remove: (id) => setPlaylists((list) => list.filter((pl) => pl.id !== id)),
      setVisibility: (id, visibility) =>
        patch(id, (pl) => setVisibilityOn(pl, visibility)),
      addClip: (id, clip) => {
        setClipsById((known) => new Map(known).set(clip.id, clip))
        patch(id, (pl) => addClipTo(pl, clip.id))
      },
      removeClip: (id, clipId) => patch(id, (pl) => removeClipFrom(pl, clipId)),
      reorderClips: (id, from, to) =>
        patch(id, (pl) => reorderClipsIn(pl, from, to)),
      setCover: (id, coverDataUrl) =>
        patch(id, (pl) => setCoverOn(pl, coverDataUrl)),
    }),
    [playlists, clipsById, create, patch]
  )

  return (
    <PlaylistsContext.Provider value={value}>
      {children}
    </PlaylistsContext.Provider>
  )
}

export function usePlaylists(): PlaylistsContextValue {
  const ctx = useContext(PlaylistsContext)
  if (!ctx)
    throw new Error("usePlaylists must be used within a PlaylistsProvider")
  return ctx
}
