import type { Metadata } from "next"

import { PlaylistLibrary } from "@/components/playlists/PlaylistLibrary"

// Playlists library (US-20.3): create, manage, and share playlists. Web-only for
// now — the data lives in a local mock store (contexts/playlists-context) until a
// `/playlists` backend lands, mirroring Explore (US-20.1) and Search (US-20.2).

export const metadata: Metadata = {
  title: "Playlists · Auto Music Studio",
  description: "Create, manage, and share playlists of songs.",
}

export default function PlaylistsPage() {
  return <PlaylistLibrary />
}
