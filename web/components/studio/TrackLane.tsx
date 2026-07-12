"use client"

import { useState, type DragEvent } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Add01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ClipBlock } from "@/components/studio/ClipBlock"
import { useStudio, type StudioTrack } from "@/contexts/studio-context"
import { xToSec } from "@/lib/timeline"

// A track row: an editable-name control strip on the left, and a drop-target
// timeline region on the right holding its ClipBlocks (US-19.1). Dropped clips
// carry {clipId,title,duration} as dataTransfer JSON (set by the workspace
// panel's drag source, US-19.1 step 5) — the x position of the drop converts
// to a start time via xToSec and lands as an ADD_CLIP.

type DroppedClipPayload = {
  clipId: string
  title: string | null
  duration: number | null
}

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
    const raw = e.dataTransfer.getData("application/json")
    if (!raw) return
    let payload: DroppedClipPayload
    try {
      payload = JSON.parse(raw)
    } catch {
      return
    }
    if (!payload?.clipId) return

    const rect = e.currentTarget.getBoundingClientRect()
    const startSec = Math.max(
      0,
      xToSec(e.clientX - rect.left, { pxPerSec, scrollSec: 0 })
    )
    dispatch({
      type: "ADD_CLIP",
      id: crypto.randomUUID(),
      trackId: track.id,
      clipId: payload.clipId,
      startSec,
      title: payload.title ?? null,
      durationSec: payload.duration ?? null,
    })
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
        className="relative min-h-16 flex-1"
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
      >
        {track.clips.map((placement) => (
          <ClipBlock
            key={placement.id}
            placement={placement}
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
