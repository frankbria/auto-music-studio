"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Add01Icon, Playlist01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { DeletePlaylistDialog } from "@/components/playlists/DeletePlaylistDialog"
import { PlaylistCard } from "@/components/playlists/PlaylistCard"
import { PlaylistFormDialog } from "@/components/playlists/PlaylistFormDialog"
import { usePlaylists } from "@/contexts/playlists-context"
import type { Playlist } from "@/lib/playlists"

// Playlists library page (US-20.3). Grid of the user's playlists with create,
// rename, and delete. State lives in the PlaylistsProvider (shared with the detail
// route). No auth gate — like Explore/Search, this is a mock-backed Stage-20 page.

type Editing = { mode: "create" | "rename"; playlist?: Playlist }

export function PlaylistLibrary() {
  const { playlists, create, rename, remove } = usePlaylists()
  const [editing, setEditing] = useState<Editing | null>(null)
  const [deleting, setDeleting] = useState<Playlist | null>(null)

  const handleSubmit = (name: string, description: string) => {
    if (editing?.mode === "rename" && editing.playlist) {
      rename(editing.playlist.id, name, description)
    } else {
      create(name, description)
    }
  }

  return (
    <div className="flex flex-col gap-6 p-8">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">Playlists</h1>
        <Button onClick={() => setEditing({ mode: "create" })}>
          <HugeiconsIcon icon={Add01Icon} size={18} />
          New playlist
        </Button>
      </div>

      {playlists.length === 0 ? (
        <div
          className="flex flex-col items-center gap-3 py-20 text-center"
          data-testid="playlists-empty"
        >
          <HugeiconsIcon
            icon={Playlist01Icon}
            size={32}
            aria-hidden
            className="text-muted-foreground"
          />
          <p className="font-medium">No playlists yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Create a playlist to curate songs and use them as inspiration for new
            generations.
          </p>
          <Button onClick={() => setEditing({ mode: "create" })}>
            <HugeiconsIcon icon={Add01Icon} size={18} />
            New playlist
          </Button>
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {playlists.map((pl) => (
            <PlaylistCard
              key={pl.id}
              playlist={pl}
              onRename={(p) => setEditing({ mode: "rename", playlist: p })}
              onDelete={(p) => setDeleting(p)}
            />
          ))}
        </div>
      )}

      <PlaylistFormDialog
        open={editing != null}
        mode={editing?.mode ?? "create"}
        initial={
          editing?.playlist
            ? {
                name: editing.playlist.name,
                description: editing.playlist.description ?? "",
              }
            : undefined
        }
        onSubmit={handleSubmit}
        onOpenChange={(open) => !open && setEditing(null)}
      />

      <DeletePlaylistDialog
        open={deleting != null}
        name={deleting?.name ?? null}
        onConfirm={() => deleting && remove(deleting.id)}
        onOpenChange={(open) => !open && setDeleting(null)}
      />
    </div>
  )
}
