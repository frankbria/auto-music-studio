"use client"

import { useEffect, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  Add01Icon,
  Loading03Icon,
  MusicNote01Icon,
  Tick02Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { ClipSearchInput } from "@/components/workspace/ClipSearchInput"
import { useDebouncedValue } from "@/hooks/use-debounced-value"
import { useDiscoveryAuth } from "@/hooks/use-discovery-auth"
import { DEFAULT_SEARCH, searchClips } from "@/lib/search"
import type { Clip } from "@/lib/workspace-clips"

// Add-songs picker (US-20.3). Searches public clips through discovery (#654);
// with no query it lists the newest. Adds are immediate (the parent records the
// clip in the store); already-added songs show a check instead of an add button,
// so the dialog can stay open to add several.

/** The result of one search; it is stale (still loading) unless `q` and `attempt` match the current ones. */
type Result = {
  q: string
  attempt: number
  clips: Clip[] | null
}

export function AddSongsDialog({
  open,
  existingIds,
  onAdd,
  onOpenChange,
}: {
  open: boolean
  existingIds: string[]
  onAdd: (clip: Clip) => void
  onOpenChange: (open: boolean) => void
}) {
  const [query, setQuery] = useState("")
  const q = useDebouncedValue(query.trim(), 300)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<Result | null>(null)
  const { ready, token } = useDiscoveryAuth()

  useEffect(() => {
    if (!open || !ready) return
    let live = true
    searchClips(
      { ...DEFAULT_SEARCH, q, sort: q ? "relevance" : "newest" },
      null,
      token()
    ).then(
      (page) => live && setResult({ q, attempt, clips: page.clips }),
      () => live && setResult({ q, attempt, clips: null })
    )
    return () => {
      live = false
    }
  }, [open, ready, q, attempt, token])

  const loading = !result || result.q !== q || result.attempt !== attempt
  const inPlaylist = new Set(existingIds)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add songs</DialogTitle>
          <DialogDescription>
            Search public songs and add them to this playlist.
          </DialogDescription>
        </DialogHeader>

        <ClipSearchInput
          value={query}
          onChange={setQuery}
          placeholder="Search songs or styles…"
          ariaLabel="Search songs to add"
        />

        <ul className="flex max-h-80 flex-col gap-1 overflow-y-auto">
          {loading ? (
            <li className="flex items-center justify-center gap-2 py-6 text-sm text-muted-foreground">
              <HugeiconsIcon
                icon={Loading03Icon}
                size={16}
                className="animate-spin"
              />
              Loading songs…
            </li>
          ) : result.clips === null ? (
            <li
              role="alert"
              className="flex items-center justify-center gap-3 py-6 text-sm"
            >
              <span className="text-muted-foreground">
                Couldn&apos;t load songs.
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setAttempt((n) => n + 1)}
              >
                Retry
              </Button>
            </li>
          ) : result.clips.length === 0 ? (
            <li className="py-6 text-center text-sm text-muted-foreground">
              No public songs found.
            </li>
          ) : (
            result.clips.map((clip) => {
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
                      onClick={() => onAdd(clip)}
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
