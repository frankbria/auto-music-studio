"use client"

import { useRef, useState, type PointerEvent } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { Flag01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover"
import { TimeRuler } from "@/components/studio/TimeRuler"
import { useStudio, type StudioMarker } from "@/contexts/studio-context"
import { snapSec, snapStepSec, xToSec } from "@/lib/timeline"

// The ruler band of the studio timeline (US-19.3): a marker strip stacked on
// the US-19.1 TimeRuler, plus the loop-region overlay. All three features
// convert clientX → seconds through this component's own box, and quantize
// through the shared snap settings, so markers, loop handles, and the seek
// ruler can't drift onto different grids.

/** Pointer movement below this is a click (open the marker editor), not a
 * drag (move the marker). */
const DRAG_THRESHOLD_PX = 3

export function RulerArea({
  pxPerSec,
  durationSec,
}: {
  pxPerSec: number
  durationSec: number
}) {
  const { state, dispatch } = useStudio()
  const ref = useRef<HTMLDivElement>(null)
  const width = durationSec * pxPerSec

  function secAtClientX(clientX: number): number {
    const rectLeft = ref.current?.getBoundingClientRect().left ?? 0
    const raw = xToSec(clientX - rectLeft, { pxPerSec, scrollSec: 0 })
    // Clamp to the timeline: a captured-pointer drag can report a clientX
    // outside the ruler, which would park the marker/handle out of reach.
    const sec = Math.min(durationSec, Math.max(0, raw))
    if (!state.snapEnabled) return sec
    // Re-clamp after snapping — when durationSec isn't on the grid, rounding
    // to the nearest line can land past the timeline end.
    return Math.min(durationSec, snapSec(sec, state.snapResolution, state.bpm))
  }

  return (
    <div
      ref={ref}
      data-testid="ruler-area"
      className="relative shrink-0"
      style={{ width }}
      onDoubleClick={(e) =>
        dispatch({
          type: "ADD_MARKER",
          id: crypto.randomUUID(),
          sec: secAtClientX(e.clientX),
          label: `Marker ${state.markers.length + 1}`,
        })
      }
    >
      <div className="relative h-5 border-b border-border/50">
        {state.markers.map((marker) => (
          <MarkerFlag
            key={marker.id}
            marker={marker}
            pxPerSec={pxPerSec}
            secAtClientX={secAtClientX}
          />
        ))}
      </div>
      <TimeRuler
        pxPerSec={pxPerSec}
        durationSec={durationSec}
        displayMode={state.displayMode}
        bpm={state.bpm}
        onSeek={(sec) => dispatch({ type: "SEEK", sec })}
      />
      {state.loopEnabled && (
        <LoopRegion
          pxPerSec={pxPerSec}
          durationSec={durationSec}
          secAtClientX={secAtClientX}
        />
      )}
    </div>
  )
}

/** A named marker rendered as a flag on the marker strip: drag to move, click
 * to open the rename/delete editor. */
function MarkerFlag({
  marker,
  pxPerSec,
  secAtClientX,
}: {
  marker: StudioMarker
  pxPerSec: number
  secAtClientX: (clientX: number) => number
}) {
  const { dispatch } = useStudio()
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(marker.label)
  const dragRef = useRef<{ downX: number; dragged: boolean } | null>(null)
  const suppressOpenRef = useRef(false)

  function commitRename() {
    const label = draft.trim()
    if (label && label !== marker.label) {
      dispatch({ type: "RENAME_MARKER", markerId: marker.id, label })
    }
    setOpen(false)
  }

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next && suppressOpenRef.current) {
          suppressOpenRef.current = false
          return
        }
        if (next) setDraft(marker.label)
        setOpen(next)
      }}
    >
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Marker: ${marker.label}`}
          className="absolute top-0 flex h-full max-w-32 cursor-grab items-center gap-0.5 text-primary outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          style={{ left: marker.sec * pxPerSec }}
          onDoubleClick={(e) => e.stopPropagation()}
          onPointerDown={(e: PointerEvent<HTMLButtonElement>) => {
            dragRef.current = { downX: e.clientX, dragged: false }
            e.currentTarget.setPointerCapture?.(e.pointerId)
          }}
          onPointerMove={(e) => {
            const drag = dragRef.current
            if (!drag) return
            if (
              !drag.dragged &&
              Math.abs(e.clientX - drag.downX) < DRAG_THRESHOLD_PX
            ) {
              return
            }
            drag.dragged = true
            dispatch({
              type: "MOVE_MARKER",
              markerId: marker.id,
              sec: secAtClientX(e.clientX),
            })
          }}
          onPointerUp={(e) => {
            // The click that ends a drag would otherwise pop the editor open.
            suppressOpenRef.current = dragRef.current?.dragged ?? false
            dragRef.current = null
            e.currentTarget.releasePointerCapture?.(e.pointerId)
          }}
          onPointerCancel={() => {
            // A cancelled drag (touch scroll, capture loss) must not leave the
            // flag tracking later hovers.
            dragRef.current = null
          }}
        >
          <HugeiconsIcon icon={Flag01Icon} size={12} className="shrink-0" />
          <span className="truncate text-[10px] font-medium">
            {marker.label}
          </span>
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-60 p-3">
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            commitRename()
          }}
        >
          <Input
            aria-label="Marker label"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={(e) => e.currentTarget.select()}
          />
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={() => {
                setOpen(false)
                dispatch({ type: "DELETE_MARKER", markerId: marker.id })
              }}
            >
              Delete
            </Button>
            <Button type="submit" size="sm">
              Rename
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  )
}

/** The loop range highlighted over the time ruler, with a draggable handle on
 * each edge (mirrors editor/SelectionHandle's pointer pattern). The band
 * itself is click-transparent so ruler seeks still work inside it. */
function LoopRegion({
  pxPerSec,
  durationSec,
  secAtClientX,
}: {
  pxPerSec: number
  durationSec: number
  secAtClientX: (clientX: number) => number
}) {
  const { state, dispatch } = useStudio()
  const left = state.loopStartSec * pxPerSec
  const width = Math.max(0, (state.loopEndSec - state.loopStartSec) * pxPerSec)

  // Arrow keys move an edge by one snap step (or 0.1s with snap off), clamped
  // to the timeline like drags are.
  const nudgeStep = state.snapEnabled
    ? snapStepSec(state.snapResolution, state.bpm)
    : 0.1
  function setEdge(edge: "start" | "end", sec: number) {
    const clamped = Math.min(durationSec, Math.max(0, sec))
    dispatch({
      type: "SET_LOOP_REGION",
      startSec: edge === "start" ? clamped : state.loopStartSec,
      endSec: edge === "end" ? clamped : state.loopEndSec,
    })
  }

  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-0 h-5">
      <div
        data-testid="loop-region"
        className="absolute top-0 h-full bg-primary/20"
        style={{ left, width }}
      />
      <LoopHandle
        edge="start"
        xPx={left}
        valueSec={state.loopStartSec}
        durationSec={durationSec}
        onMoveClientX={(clientX) => setEdge("start", secAtClientX(clientX))}
        onNudge={(delta) => setEdge("start", state.loopStartSec + delta * nudgeStep)}
      />
      <LoopHandle
        edge="end"
        xPx={left + width}
        valueSec={state.loopEndSec}
        durationSec={durationSec}
        onMoveClientX={(clientX) => setEdge("end", secAtClientX(clientX))}
        onNudge={(delta) => setEdge("end", state.loopEndSec + delta * nudgeStep)}
      />
    </div>
  )
}

function LoopHandle({
  edge,
  xPx,
  valueSec,
  durationSec,
  onMoveClientX,
  onNudge,
}: {
  edge: "start" | "end"
  xPx: number
  valueSec: number
  durationSec: number
  onMoveClientX: (clientX: number) => void
  /** Arrow-key adjustment: delta is -1 (left) or +1 (right) snap steps. */
  onNudge: (delta: number) => void
}) {
  const dragging = useRef(false)
  return (
    <div
      role="slider"
      aria-label={`Loop ${edge} handle`}
      aria-orientation="horizontal"
      aria-valuemin={0}
      aria-valuemax={durationSec}
      aria-valuenow={valueSec}
      tabIndex={0}
      className="pointer-events-auto absolute top-0 z-10 h-full w-2 -translate-x-1/2 cursor-ew-resize touch-none"
      style={{ left: xPx }}
      onDoubleClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") {
          e.preventDefault()
          onNudge(-1)
        } else if (e.key === "ArrowRight") {
          e.preventDefault()
          onNudge(1)
        }
      }}
      onPointerDown={(e) => {
        e.stopPropagation() // don't seek the ruler underneath
        e.currentTarget.setPointerCapture?.(e.pointerId)
        dragging.current = true
      }}
      onPointerMove={(e) => {
        if (dragging.current) onMoveClientX(e.clientX)
      }}
      onPointerUp={(e) => {
        dragging.current = false
        e.currentTarget.releasePointerCapture?.(e.pointerId)
      }}
      onPointerCancel={() => {
        dragging.current = false
      }}
    >
      <span className="absolute top-0 left-1/2 h-full w-0.5 -translate-x-1/2 bg-primary" />
    </div>
  )
}
