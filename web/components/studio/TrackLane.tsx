"use client"

import { useState, type DragEvent } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Add01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ClipBlock } from "@/components/studio/ClipBlock"
import { useStudio, type StudioTrack } from "@/contexts/studio-context"
import { parseClipDragData } from "@/lib/clip-drag"
import { xToSec } from "@/lib/timeline"
import { cn } from "@/lib/utils"

// A track row: an editable-name control strip on the left, and a drop-target
// timeline region on the right holding its ClipBlocks (US-19.1). Accepts two
// drop kinds (lib/clip-drag.ts): a fresh clip dragged in from the workspace
// panel ("add") or an existing placement being repositioned from this or
// another lane ("move") — the x position of the drop converts to a start time
// via xToSec either way.

export function TrackLane({
  track,
  pxPerSec,
  token,
}: {
  track: StudioTrack
  pxPerSec: number
  token: string | null
}) {
  const { dispatch } = useStudio()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(track.name)
  const [dragOver, setDragOver] = useState(false)

  function startEdit() {
    setDraft(track.name)
    setEditing(true)
  }

  function commitEdit() {
    setEditing(false)
    const next = draft.trim()
    if (next && next !== track.name) {
      dispatch({ type: "RENAME_TRACK", trackId: track.id, name: next })
    }
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    const payload = parseClipDragData(e.dataTransfer)
    if (!payload) return

    const rect = e.currentTarget.getBoundingClientRect()
    const startSec = Math.max(
      0,
      xToSec(e.clientX - rect.left, { pxPerSec, scrollSec: 0 })
    )

    if (payload.kind === "add") {
      dispatch({
        type: "ADD_CLIP",
        id: crypto.randomUUID(),
        trackId: track.id,
        clipId: payload.clipId,
        startSec,
        title: payload.title,
        durationSec: payload.duration,
      })
    } else {
      dispatch({
        type: "MOVE_CLIP",
        trackId: track.id,
        placementId: payload.placementId,
        startSec,
      })
    }
  }

  return (
    <div data-testid="track-lane" className="flex border-b border-border">
      <div
        className="flex w-40 shrink-0 items-center p-2"
        style={{ borderLeft: `4px solid ${track.color}` }}
      >
        {editing ? (
          <Input
            aria-label="Track name"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={(e) => e.currentTarget.select()}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur()
              else if (e.key === "Escape") {
                setEditing(false)
              }
            }}
            className="h-7"
          />
        ) : (
          <button
            type="button"
            aria-label="Edit track name"
            onClick={startEdit}
            className="truncate text-left text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            {track.name}
          </button>
        )}
      </div>

      <div
        role="region"
        aria-label={`${track.name} timeline`}
        className={cn("relative min-h-16 flex-1", dragOver && "bg-accent/40")}
        onDragOver={(e) => e.preventDefault()}
        onDragEnter={() => setDragOver(true)}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      >
        {track.clips.map((placement) => (
          <ClipBlock
            key={placement.id}
            placement={placement}
            trackId={track.id}
            pxPerSec={pxPerSec}
            color={track.color}
            token={token}
          />
        ))}
      </div>
    </div>
  )
}

/** Appends a new track to the studio (US-19.1). */
export function AddTrackButton() {
  const { dispatch } = useStudio()
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={() => dispatch({ type: "ADD_TRACK", id: crypto.randomUUID() })}
    >
      <HugeiconsIcon icon={Add01Icon} data-icon="inline-start" />
      Add Track
    </Button>
  )
}
