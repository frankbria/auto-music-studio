import { PlaylistsProvider } from "@/contexts/playlists-context"

// Wraps the /playlists subtree (list + detail) in the shared in-memory store so
// both routes read and mutate one reactive source (US-20.3). Kept as a layout so
// navigating between the library and a detail page doesn't reset playlist state.

export default function PlaylistsLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return <PlaylistsProvider>{children}</PlaylistsProvider>
}
