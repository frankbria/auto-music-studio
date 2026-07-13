"use client"

import { useState, type DragEvent } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Add01Icon, AiMagicIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { Slider } from "@/components/ui/slider"
import { ClipBlock } from "@/components/studio/ClipBlock"
import { TrackRegenerateDialog } from "@/components/studio/TrackRegenerateDialog"
import { useStudio, type StudioTrack } from "@/contexts/studio-context"
import { parseClipDragData, readDragTrackType } from "@/lib/clip-drag"
import {
  VOLUME_DB_MAX,
  VOLUME_DB_MIN,
  formatVolumeDb,
  isTrackSilenced,
} from "@/lib/track-audio"
import {
  TRACK_STRIP_PX,
  snapSec,
  snapStepSec,
  xToSec,
  type SnapResolution,
} from "@/lib/timeline"
import {
  TRACK_TYPES,
  TRACK_TYPE_ORDER,
  placementPlaybackRate,
} from "@/lib/track-types"
import { cn } from "@/lib/utils"

// A track row: an editable-name control strip on the left, and a drop-target
// timeline region on the right holding its ClipBlocks (US-19.1). Accepts two
// drop kinds (lib/clip-drag.ts): a fresh clip dragged in from the workspace
// panel ("add") or an existing placement being repositioned from this or
// another lane ("move") — the x position of the drop converts to a start time
// via xToSec either way. Tracks are typed (US-19.2): mismatched clips get
// invalid-drop feedback during dragover, and the reducer rejects them
// authoritatively on drop.

/** Valid/invalid drop feedback while a drag hovers the lane. A drag with no
 * track-type entry (external files, unit tests) reads as valid — the drop
 * handler and reducer still validate the actual payload. */
type DragOverState = null | "valid" | "invalid"

/** Grid lines below this spacing are visual noise, so they aren't drawn —
 * snapping itself still applies at the full resolution. */
const MIN_GRID_LINE_PX = 8

/** Swatches offered by the track color selector (US-19.4). */
const TRACK_COLORS = [
  { name: "Rose", value: "#f43f5e" },
  { name: "Orange", value: "#f97316" },
  { name: "Amber", value: "#f59e0b" },
  { name: "Emerald", value: "#10b981" },
  { name: "Sky", value: "#0ea5e9" },
  { name: "Violet", value: "#8b5cf6" },
  { name: "Pink", value: "#ec4899" },
  { name: "Slate", value: "#64748b" },
]

function panLabel(pan: number): string {
  if (pan === 0) return "C"
  return pan < 0 ? `L${-pan}` : `R${pan}`
}

/** One vertical line per snap grid step, drawn in CSS instead of DOM nodes
 * (US-19.3) — a repeating gradient scales with zoom for free. */
function gridBackground(
  state: { snapEnabled: boolean; snapResolution: SnapResolution; bpm: number },
  pxPerSec: number
): React.CSSProperties | undefined {
  if (!state.snapEnabled) return undefined
  const stepPx = snapStepSec(state.snapResolution, state.bpm) * pxPerSec
  if (stepPx < MIN_GRID_LINE_PX) return undefined
  return {
    backgroundImage: `repeating-linear-gradient(to right, var(--border) 0, var(--border) 1px, transparent 1px, transparent ${stepPx}px)`,
  }
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
  const { state, dispatch } = useStudio()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(track.name)
  const [dragOver, setDragOver] = useState<DragOverState>(null)
  const [regenOpen, setRegenOpen] = useState(false)
  const typeConfig = TRACK_TYPES[track.trackType]
  // Dim the lane whenever the engine would silence it — same predicate the
  // audio graph uses, so sight and sound can't diverge.
  const anySolo = state.tracks.some((t) => t.solo)
  const silenced = isTrackSilenced(track, anySolo)

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

  function dragValidity(e: DragEvent<HTMLDivElement>): DragOverState {
    const dragType = e.dataTransfer ? readDragTrackType(e.dataTransfer) : null
    return dragType && dragType !== track.trackType ? "invalid" : "valid"
  }

  function onDragOver(e: DragEvent<HTMLDivElement>) {
    if (dragValidity(e) === "invalid") {
      // No preventDefault → the browser disallows the drop and shows the
      // platform's no-drop cursor; the tinted lane says why.
      return
    }
    e.preventDefault()
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(null)
    const payload = parseClipDragData(e.dataTransfer)
    if (!payload) return

    const rect = e.currentTarget.getBoundingClientRect()
    const cursorSec = xToSec(e.clientX - rect.left, { pxPerSec, scrollSec: 0 })

    // Snap-to-grid (US-19.3) quantizes where the clip's left edge lands — for
    // a move that's the grabbed point minus its offset, so the edge (not the
    // cursor) snaps to the grid line.
    function place(rawSec: number): number {
      const sec = Math.max(0, rawSec)
      return state.snapEnabled
        ? snapSec(sec, state.snapResolution, state.bpm)
        : sec
    }

    if (payload.kind === "add") {
      dispatch({
        type: "ADD_CLIP",
        id: crypto.randomUUID(),
        trackId: track.id,
        clipId: payload.clipId,
        startSec: place(cursorSec),
        title: payload.title,
        durationSec: payload.duration,
        generationMode: payload.generationMode,
        clipBpm: payload.bpm,
      })
    } else {
      dispatch({
        type: "MOVE_CLIP",
        trackId: track.id,
        placementId: payload.placementId,
        // Keep the grabbed point under the cursor: the clip's left edge lands
        // grabOffsetSec before it.
        startSec: place(cursorSec - payload.grabOffsetSec),
      })
    }
  }

  return (
    <div data-testid="track-lane" className="flex border-b border-border">
      <div
        data-testid="track-strip"
        className="flex shrink-0 flex-col justify-center gap-1 p-2"
        style={{
          width: TRACK_STRIP_PX,
          borderLeft: `4px solid ${track.color}`,
        }}
      >
        <div className="flex items-center gap-1.5">
          <span
            // aria-label is prohibited on role=generic (a bare span); role="img"
            // makes the accessible name spec-valid for screenreaders.
            role="img"
            aria-label={`${typeConfig.label} track`}
            className="shrink-0"
            style={{ color: track.color }}
          >
            <HugeiconsIcon icon={typeConfig.icon} size={16} />
          </span>
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
              className="min-w-0 flex-1 truncate text-left text-sm font-medium outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {track.name}
            </button>
          )}
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label="Track color"
                className="size-4 shrink-0 rounded-full border border-border outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                style={{ backgroundColor: track.color }}
              />
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-2">
              <div className="grid grid-cols-4 gap-1.5">
                {TRACK_COLORS.map((c) => (
                  <button
                    key={c.value}
                    type="button"
                    aria-label={`Color ${c.name}`}
                    onClick={() =>
                      dispatch({
                        type: "SET_TRACK_COLOR",
                        trackId: track.id,
                        color: c.value,
                      })
                    }
                    className="size-5 rounded-full border border-border outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
                    style={{ backgroundColor: c.value }}
                  />
                ))}
              </div>
            </PopoverContent>
          </Popover>
        </div>

        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="Mute track"
            aria-pressed={track.muted}
            onClick={() =>
              dispatch({ type: "TOGGLE_TRACK_MUTE", trackId: track.id })
            }
            className={cn(
              "text-xs font-semibold",
              track.muted && "bg-destructive/15 text-destructive"
            )}
          >
            M
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="Solo track"
            aria-pressed={track.solo}
            onClick={() =>
              dispatch({ type: "TOGGLE_TRACK_SOLO", trackId: track.id })
            }
            className={cn(
              "text-xs font-semibold",
              track.solo && "bg-amber-500/20 text-amber-600"
            )}
          >
            S
          </Button>
          <Slider
            aria-label="Track volume"
            title={formatVolumeDb(track.volumeDb)}
            min={VOLUME_DB_MIN}
            max={VOLUME_DB_MAX}
            step={1}
            value={[track.volumeDb]}
            onValueChange={([v]) =>
              dispatch({
                type: "SET_TRACK_VOLUME",
                trackId: track.id,
                volumeDb: v,
              })
            }
            className="min-w-0 flex-1"
          />
          <Popover>
            <PopoverTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="xs"
                aria-label="Track pan"
                className="min-w-7 px-1 text-xs tabular-nums text-muted-foreground"
              >
                {panLabel(track.pan)}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-44 p-3">
              <Slider
                aria-label="Pan"
                min={-100}
                max={100}
                step={1}
                value={[track.pan]}
                onValueChange={([v]) =>
                  dispatch({ type: "SET_TRACK_PAN", trackId: track.id, pan: v })
                }
              />
            </PopoverContent>
          </Popover>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="Regenerate track"
            // Audio (uploads) and vocal (extracted stems) clips can't be
            // produced by prompt generation, so their inferred type would
            // never land on this track (US-19.2 strict typing).
            disabled={track.trackType !== "ai" && track.trackType !== "loop"}
            title={
              track.trackType !== "ai" && track.trackType !== "loop"
                ? "Regeneration is available for AI and Sound/Loop tracks"
                : undefined
            }
            onClick={() => setRegenOpen(true)}
          >
            <HugeiconsIcon icon={AiMagicIcon} size={14} />
          </Button>
        </div>
        {regenOpen && (
          <TrackRegenerateDialog
            track={track}
            token={token}
            onClose={() => setRegenOpen(false)}
          />
        )}
      </div>

      <div
        role="region"
        aria-label={`${track.name} timeline`}
        className={cn(
          "relative min-h-16 flex-1",
          silenced && "opacity-50",
          dragOver === "valid" && "bg-accent/40",
          dragOver === "invalid" && "bg-destructive/10"
        )}
        style={gridBackground(state, pxPerSec)}
        onDragOver={onDragOver}
        onDragEnter={(e) => setDragOver(dragValidity(e))}
        onDragLeave={(e) => {
          // A dragLeave also fires when the pointer moves onto a child
          // ClipBlock (still within this lane) — only clear once it's truly
          // left the lane's own box, or the highlight flickers on every clip
          // it drags over.
          if (!e.currentTarget.contains(e.relatedTarget as Node)) {
            setDragOver(null)
          }
        }}
        onDrop={onDrop}
      >
        {track.clips.map((placement) => (
          <ClipBlock
            key={placement.id}
            placement={placement}
            pxPerSec={pxPerSec}
            color={track.color}
            token={token}
            trackType={track.trackType}
            playbackRate={placementPlaybackRate(
              placement.clipBpm,
              track.trackType,
              state.bpm
            )}
          />
        ))}
      </div>
    </div>
  )
}

/** Appends a new track of the chosen type to the studio (US-19.1, US-19.2). */
export function AddTrackButton() {
  const { dispatch } = useStudio()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="outline" size="sm">
          <HugeiconsIcon icon={Add01Icon} data-icon="inline-start" />
          Add Track
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start">
        {TRACK_TYPE_ORDER.map((type) => {
          const cfg = TRACK_TYPES[type]
          return (
            <DropdownMenuItem
              key={type}
              onSelect={() =>
                dispatch({
                  type: "ADD_TRACK",
                  id: crypto.randomUUID(),
                  trackType: type,
                })
              }
            >
              <span style={{ color: cfg.color }}>
                <HugeiconsIcon icon={cfg.icon} size={16} />
              </span>
              <span className="flex flex-col">
                <span>{cfg.label}</span>
                <span className="text-xs text-muted-foreground">
                  {cfg.description}
                </span>
              </span>
            </DropdownMenuItem>
          )
        })}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
