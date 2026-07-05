"use client"

import { formatTime } from "@/lib/clips"
import { visibleTicks, type Viewport } from "@/lib/waveform-viewport"

// Time ruler for the waveform editor (US-18.1). Renders major ticks + mm:ss
// labels for the current viewport; the tick interval adapts to zoom (see
// chooseTickInterval), so labels stay ~80px apart from full-clip overview down
// to sub-second detail. DOM (absolutely-positioned spans) rather than canvas so
// the labels are real text — selectable, testable, and crisp at any DPR.

export function TimeRuler({
  viewport,
  width,
  duration,
}: {
  viewport: Viewport
  width: number
  duration: number
}) {
  const ticks = width > 0 ? visibleTicks(viewport, width, duration) : []

  return (
    <div
      className="relative h-5 w-full select-none border-b border-border text-[10px] text-muted-foreground"
      aria-hidden="true"
    >
      {ticks.map((tick) => (
        <div
          key={tick.sec}
          className="absolute top-0 flex h-full flex-col items-start"
          style={{ left: `${tick.x}px` }}
        >
          <span className="h-1.5 w-px bg-border" />
          <span className="pl-1 tabular-nums">{formatTime(tick.sec)}</span>
        </div>
      ))}
    </div>
  )
}
