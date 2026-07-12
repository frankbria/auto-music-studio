"use client"

import type { MouseEvent } from "react"

import {
  DEFAULT_BPM,
  timelineTicks,
  xToSec,
  type DisplayMode,
} from "@/lib/timeline"

// Time ruler for the Studio multi-track timeline (US-19.1). Unlike the
// waveform editor's TimeRuler, the studio timeline isn't virtual-scrolled — it
// renders at full content width (durationSec * pxPerSec) and relies on the
// track area's native horizontal scrollbar, so scrollSec here is always 0.
// A click seeks the playhead (xToSec of the click's x); `role="img"` + a label
// (rather than aria-hidden) mirrors WaveformCanvas's precedent for a visual
// widget that's also directly interactive.

export function TimeRuler({
  pxPerSec,
  durationSec,
  displayMode,
  bpm = DEFAULT_BPM,
  onSeek,
}: {
  pxPerSec: number
  durationSec: number
  displayMode: DisplayMode
  bpm?: number
  onSeek?: (sec: number) => void
}) {
  const width = durationSec * pxPerSec
  const ticks =
    width > 0
      ? timelineTicks(
          { pxPerSec, scrollSec: 0 },
          width,
          durationSec,
          displayMode,
          bpm
        )
      : []

  function handleClick(e: MouseEvent<HTMLDivElement>) {
    if (!onSeek) return
    const rect = e.currentTarget.getBoundingClientRect()
    onSeek(
      Math.max(0, xToSec(e.clientX - rect.left, { pxPerSec, scrollSec: 0 }))
    )
  }

  return (
    <div
      role="img"
      aria-label="Timeline"
      className="relative h-5 shrink-0 cursor-pointer border-b border-border text-[10px] text-muted-foreground select-none"
      style={{ width }}
      onClick={handleClick}
    >
      {ticks.map((tick) => (
        <div
          key={tick.sec}
          className="absolute top-0 flex h-full flex-col items-start"
          style={{ left: `${tick.x}px` }}
        >
          <span className="h-1.5 w-px bg-border" />
          <span className="pl-1 tabular-nums">{tick.label}</span>
        </div>
      ))}
    </div>
  )
}
