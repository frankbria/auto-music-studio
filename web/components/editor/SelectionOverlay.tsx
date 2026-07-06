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

export function SelectionOverlay({
  selection,
  viewport,
  width,
  height,
  onAdjust,
}: {
  selection: Region | null
  viewport: Viewport
  width: number
  height: number
  /** A handle was dragged: set `edge` to the (unclamped) time under the pointer. */
  onAdjust: (edge: "start" | "end", sec: number) => void
}) {
  const ref = useRef<HTMLDivElement>(null)

  if (!selection) return null

  const startX = secToX(selection.startSec, viewport)
  const endX = secToX(selection.endSec, viewport)
  // Nothing to draw if the whole region sits off either side of the viewport.
  if (endX < 0 || startX > width) return null

  const left = Math.max(0, startX)
  const right = Math.min(width, endX)

  const clientXToSec = (clientX: number) => {
    const rectLeft = ref.current?.getBoundingClientRect().left ?? 0
    return xToSec(clientX - rectLeft, viewport)
  }

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
      {startX >= 0 && startX <= width && (
        <div className="pointer-events-auto">
          <SelectionHandle
            xPx={startX}
            height={height}
            edge="start"
            onMoveClientX={(c) => onAdjust("start", clientXToSec(c))}
          />
        </div>
      )}
      {endX >= 0 && endX <= width && (
        <div className="pointer-events-auto">
          <SelectionHandle
            xPx={endX}
            height={height}
            edge="end"
            onMoveClientX={(c) => onAdjust("end", clientXToSec(c))}
          />
        </div>
      )}
    </div>
  )
}
