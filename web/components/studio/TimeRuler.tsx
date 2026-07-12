"use client"

import { DEFAULT_BPM, timelineTicks, type DisplayMode } from "@/lib/timeline"

// Time ruler for the Studio multi-track timeline (US-19.1). Unlike the
// waveform editor's TimeRuler, the studio timeline isn't virtual-scrolled — it
// renders at full content width (durationSec * pxPerSec) and relies on the
// track area's native horizontal scrollbar, so scrollSec here is always 0.

export function TimeRuler({
  pxPerSec,
  durationSec,
  displayMode,
  bpm = DEFAULT_BPM,
}: {
  pxPerSec: number
  durationSec: number
  displayMode: DisplayMode
  bpm?: number
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

  return (
    <div
      className="relative h-5 shrink-0 border-b border-border text-[10px] text-muted-foreground select-none"
      style={{ width }}
      aria-hidden="true"
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
