"use client"

import { useRef } from "react"

import { SelectionHandle } from "@/components/editor/SelectionHandle"
import { secToX, xToSec, type Viewport } from "@/lib/waveform-viewport"
import type { Region } from "@/lib/waveform-edit"

// The visual selection layer (US-18.2): a translucent highlight over the
// selected time range plus a draggable handle on each edge. Positioned over the
// canvas (same left origin / width), so it converts times through the same
// secToX/xToSec the canvas uses. Renders nothing when there's no selection or
// when the region is scrolled entirely out of view.
//
// Handles stay mounted (with their x clamped to the viewport) whenever the
// overlay renders — unmounting one mid-drag would drop its pointer capture and
// freeze the drag at the viewport edge.

export function SelectionOverlay({
  selection,
  viewport,
  width,
  height,
  duration,
  onAdjust,
}: {
  selection: Region | null
  viewport: Viewport
  width: number
  height: number
  duration: number
  /** A handle moved (drag or Arrow key): set `edge` to the new time. */
  onAdjust: (edge: "start" | "end", sec: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  if (!selection) return null

  const startX = secToX(selection.startSec, viewport)
  const endX = secToX(selection.endSec, viewport)
  // Nothing to draw if the whole region sits off either side of the viewport.
  if (endX < 0 || startX > width) return null

  const clamp = (x: number) => Math.max(0, Math.min(width, x))
  const left = clamp(startX)
  const right = clamp(endX)

  const clientXToSec = (clientX: number) => {
    const rectLeft = ref.current?.getBoundingClientRect().left ?? 0
    return xToSec(clientX - rectLeft, viewport)
  }
  const nudge = (edge: "start" | "end", deltaSec: number) =>
    onAdjust(edge, (edge === "start" ? selection.startSec : selection.endSec) + deltaSec)

  return (
    <div
      ref={ref}
      className="pointer-events-none absolute inset-0 z-10"
      data-testid="selection-overlay"
    >
      <div
        className="absolute top-0 bg-primary/25"
        style={{ left, width: Math.max(0, right - left), height }}
      />
      <div className="pointer-events-auto">
        <SelectionHandle
          xPx={left}
          height={height}
          edge="start"
          valueSec={selection.startSec}
          minSec={0}
          maxSec={selection.endSec}
          onMoveClientX={(c) => onAdjust("start", clientXToSec(c))}
          onNudge={nudge}
        />
        <SelectionHandle
          xPx={right}
          height={height}
          edge="end"
          valueSec={selection.endSec}
          minSec={selection.startSec}
          maxSec={duration}
          onMoveClientX={(c) => onAdjust("end", clientXToSec(c))}
          onNudge={nudge}
        />
      </div>
    </div>
  )
}
