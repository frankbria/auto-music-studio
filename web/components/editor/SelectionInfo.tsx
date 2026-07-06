"use client"

import type { Region } from "@/lib/waveform-edit"

// Selection readout (US-18.2): start / end / duration for the current region.
// Formatted as m:ss.mmm — audio edits are sub-second, so a 300ms selection must
// not read as "0:00". Renders nothing when there's no selection.

/** m:ss.mmm. Derived from integer total-ms so seconds carry with no FP flooring
 *  artifact (8.2s → "0:08.200", not "0:08.199") and ms never rolls to 1000. */
function fmt(sec: number): string {
  const totalMs = Math.round(Math.max(0, sec) * 1000)
  const ms = totalMs % 1000
  const totalSec = Math.floor(totalMs / 1000)
  const m = Math.floor(totalSec / 60)
  const s = totalSec % 60
  return `${m}:${s.toString().padStart(2, "0")}.${ms.toString().padStart(3, "0")}`
}

export function SelectionInfo({ selection }: { selection: Region | null }) {
  if (!selection) return null
  const duration = Math.max(0, selection.endSec - selection.startSec)

  return (
    <div
      className="flex gap-4 text-xs text-muted-foreground tabular-nums"
      data-testid="selection-info"
    >
      <span>
        Start <span className="text-foreground">{fmt(selection.startSec)}</span>
      </span>
      <span>
        End <span className="text-foreground">{fmt(selection.endSec)}</span>
      </span>
      <span>
        Duration <span className="text-foreground">{fmt(duration)}</span>
      </span>
    </div>
  )
}
