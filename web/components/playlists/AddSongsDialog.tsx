"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Add01Icon, MusicNote01Icon, Tick02Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ClipSearchInput } from "@/components/workspace/ClipSearchInput"
import { getAllClips } from "@/lib/explore"
import type { Clip } from "@/lib/workspace-clips"

// Add-songs picker (US-20.3). Songs come from the same discovery pool as Explore.
// Adds are immediate (the parent appends via the store); already-added songs show a
// check instead of an add button, so the dialog can stay open to add several.

function matches(clip: Clip, needle: string): boolean {
  if (!needle) return true
  const hay = `${clip.title ?? ""} ${clip.style_tags.join(" ")}`.toLowerCase()
  return hay.includes(needle)
}

export function AddSongsDialog({
  open,
  existingIds,
  onAdd,
  onOpenChange,
}: {
  open: boolean
  existingIds: string[]
  onAdd: (clipId: string) => void
  onOpenChange: (open: boolean) => void
}) {
  const [query, setQuery] = useState("")
  const inPlaylist = new Set(existingIds)
  const needle = query.trim().toLowerCase()
  const results = getAllClips().filter((c) => matches(c, needle))

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add songs</DialogTitle>
          <DialogDescription>
            Search the catalog and add songs to this playlist.
          </DialogDescription>
        </DialogHeader>

        <ClipSearchInput
          value={query}
          onChange={setQuery}
          placeholder="Search songs or styles…"
          ariaLabel="Search songs to add"
        />

        <ul className="flex max-h-80 flex-col gap-1 overflow-y-auto">
          {results.length === 0 ? (
            <li className="py-6 text-center text-sm text-muted-foreground">
              No songs match &ldquo;{query}&rdquo;.
            </li>
          ) : (
            results.map((clip) => {
              const added = inPlaylist.has(clip.id)
              return (
                <li
                  key={clip.id}
                  className="flex items-center gap-3 rounded-md px-2 py-2 hover:bg-muted"
                >
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                    <HugeiconsIcon icon={MusicNote01Icon} size={16} />
                  </span>
                  <div className="flex min-w-0 flex-1 flex-col">
                    <span className="truncate text-sm font-medium">
                      {clip.title ?? "Untitled clip"}
                    </span>
                    <span className="truncate text-xs text-muted-foreground">
                      {clip.style_tags.join(", ")}
                    </span>
                  </div>
                  {added ? (
                    <span className="flex items-center gap-1 text-xs text-muted-foreground">
                      <HugeiconsIcon icon={Tick02Icon} size={14} />
                      Added
                    </span>
                  ) : (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => onAdd(clip.id)}
                      aria-label={`Add ${clip.title ?? "song"}`}
                    >
                      <HugeiconsIcon icon={Add01Icon} size={14} />
                      Add
                    </Button>
                  )}
                </li>
              )
            })
          )}
        </ul>
      </DialogContent>
    </Dialog>
  )
}
