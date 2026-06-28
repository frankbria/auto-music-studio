"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Playlist01Icon } from "@hugeicons/core-free-icons"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { MOCK_PLAYLISTS, type InspirationSelection } from "@/lib/audio-inputs"

/**
 * Add Inspiration modal (US-16.8): reference one of the user's playlists as
 * inspirational context. Playlists have no backend yet, so the list comes from
 * MOCK_PLAYLISTS; selecting one closes the modal via `onSelect`.
 */
export function AddInspirationModal({
  open,
  onOpenChange,
  onSelect,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (selection: InspirationSelection) => void
}) {
  const playlists = MOCK_PLAYLISTS

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add inspiration</DialogTitle>
          <DialogDescription>
            Reference a playlist to inspire your generation.
          </DialogDescription>
        </DialogHeader>

        {playlists.length === 0 ? (
          <p className="px-2 py-6 text-sm text-muted-foreground">
            No playlists yet. Create one in your Library.
          </p>
        ) : (
          <ul className="flex max-h-80 flex-col gap-1 overflow-y-auto">
            {playlists.map((playlist) => (
              <li key={playlist.id}>
                <button
                  type="button"
                  onClick={() => {
                    onSelect({ id: playlist.id, name: playlist.name })
                    onOpenChange(false)
                  }}
                  className="flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-muted"
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <HugeiconsIcon icon={Playlist01Icon} size={18} />
                  </span>
                  <span className="flex flex-col">
                    <span className="text-sm font-medium">{playlist.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {playlist.trackCount} tracks
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
