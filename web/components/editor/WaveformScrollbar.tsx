"use client"

import { maxScrollSec, type Viewport } from "@/lib/waveform-viewport"

// Horizontal scrollbar for the waveform editor (US-18.1). Appears only when the
// clip is zoomed past the viewport width (otherwise the whole clip is visible
// and there's nothing to scroll). A plain range input — click, drag, and
// keyboard scrolling come for free and stay in sync with wheel/drag panning on
// the canvas because both write the same `scrollSec`.

export function WaveformScrollbar({
  viewport,
  width,
  duration,
  onScroll,
}: {
  viewport: Viewport
  width: number
  duration: number
  onScroll: (scrollSec: number) => void
}) {
  const max = maxScrollSec(duration, viewport.pxPerSec, width)
  if (max <= 0) return null

  return (
    <input
      type="range"
      aria-label="Scroll waveform"
      min={0}
      max={max}
      step={Math.max(0.01, max / 500)}
      value={Math.min(viewport.scrollSec, max)}
      onChange={(e) => onScroll(Number(e.target.value))}
      className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
    />
  )
}
