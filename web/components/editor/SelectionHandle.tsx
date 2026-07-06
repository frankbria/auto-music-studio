"use client"

import { useRef } from "react"

// A draggable edge of the selection region (US-18.2). Reused for both the start
// and end boundary. A thin vertical line with a wider invisible grab target and
// an ew-resize cursor. Pointer drags report the raw clientX (the overlay
// converts it to a time and clamps); Arrow keys nudge the edge by NUDGE_SEC so
// the boundary is keyboard-adjustable too. It's a real ARIA slider over the
// time axis, so aria-value* carry seconds — not pixels.

const NUDGE_SEC = 0.05

export function SelectionHandle({
  xPx,
  height,
  edge,
  valueSec,
  minSec,
  maxSec,
  onMoveClientX,
  onNudge,
}: {
  xPx: number
  height: number
  edge: "start" | "end"
  valueSec: number
  minSec: number
  maxSec: number
  onMoveClientX: (clientX: number) => void
  onNudge: (edge: "start" | "end", deltaSec: number) => void
}) {
  const dragging = useRef(false)

  return (
    <div
      role="slider"
      aria-label={`Selection ${edge} handle`}
      aria-orientation="horizontal"
      aria-valuemin={minSec}
      aria-valuemax={maxSec}
      aria-valuenow={valueSec}
      tabIndex={0}
      data-edge={edge}
      onKeyDown={(e) => {
        if (e.key === "ArrowLeft") {
          e.preventDefault()
          onNudge(edge, -NUDGE_SEC)
        } else if (e.key === "ArrowRight") {
          e.preventDefault()
          onNudge(edge, NUDGE_SEC)
        }
      }}
      onPointerDown={(e) => {
        e.stopPropagation() // don't start a new selection on the canvas below
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
      className="absolute top-0 z-20 w-2 -translate-x-1/2 cursor-ew-resize touch-none"
      style={{ left: xPx, height }}
    >
      <span className="absolute left-1/2 top-0 h-full w-px -translate-x-1/2 bg-primary" />
    </div>
  )
}
