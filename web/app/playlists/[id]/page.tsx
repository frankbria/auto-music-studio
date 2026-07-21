"use client"

import { useParams } from "next/navigation"

import { PlaylistDetail } from "@/components/playlists/PlaylistDetail"

// Playlist detail route /playlists/[id] (US-20.3). Thin shim: pull the id from the
// route and hand off to PlaylistDetail, which reads the shared store and owns the
// songs, cover, visibility, share, and inspiration UI.

export default function PlaylistDetailPage() {
  const params = useParams<{ id: string }>()
  const id = params?.id
  if (!id) return null
  return <PlaylistDetail playlistId={id} />
}
