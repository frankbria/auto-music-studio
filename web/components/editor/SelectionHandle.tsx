"use client"

import { useRef } from "react"

// A draggable edge of the selection region (US-18.2). Reused for both the start
// and end boundary. A thin vertical line with a wider invisible grab target and
// an ew-resize cursor. It only knows about screen pixels: on drag it reports the
// raw pointer clientX; the overlay converts that to a time via the viewport and
// clamps it so the two edges can't cross.

export function SelectionHandle({
  xPx,
  height,
  edge,
  onMoveClientX,
}: {
  xPx: number
  height: number
  edge: "start" | "end"
  onMoveClientX: (clientX: number) => void
}) {
  const dragging = useRef(false)

  return (
    <div
      role="slider"
      aria-label={`Selection ${edge} handle`}
      aria-orientation="vertical"
      aria-valuenow={Math.round(xPx)}
      tabIndex={0}
      data-edge={edge}
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
