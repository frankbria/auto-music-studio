"use client"

import { useMemo, useState } from "react"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Slider } from "@/components/ui/slider"
import { formatTime } from "@/lib/clips"
import {
  DEFAULT_TARGET_DURATION,
  planSections,
  TARGET_DURATION_MAX,
  TARGET_DURATION_MIN,
} from "@/lib/song-structure"

// Step 1 of the Get Full Song wizard (US-17.4): show the planned structure and
// let the user pick a target length before any generation runs. The section
// breakdown recomputes live from planSections() (the ported backend planner) as
// the target slider moves; "Start" hands the final plan + target up to the flow.

export function StructurePreviewStep({
  seedTitle,
  seedDuration,
  onStart,
}: {
  seedTitle: string
  seedDuration: number
  onStart: (targetDuration: number) => void
}) {
  const [target, setTarget] = useState(DEFAULT_TARGET_DURATION)
  const sections = useMemo(
    () => planSections(seedDuration, target),
    [seedDuration, target]
  )
  const longest = sections.reduce((m, s) => Math.max(m, s.durationSeconds), 0)

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-lg border border-border bg-muted/40 p-3 text-sm">
        <p className="font-medium">{seedTitle}</p>
        <p className="text-xs text-muted-foreground">
          Seed clip · {formatTime(seedDuration)}
        </p>
      </div>

      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="full-song-target">Target length</Label>
          <span className="text-sm tabular-nums text-muted-foreground">
            {formatTime(target)}
          </span>
        </div>
        <Slider
          id="full-song-target"
          min={TARGET_DURATION_MIN}
          max={TARGET_DURATION_MAX}
          step={10}
          value={[target]}
          onValueChange={([v]) => setTarget(v)}
        />
      </div>

      <div className="flex flex-col gap-1.5">
        <p className="text-sm font-medium">Planned structure</p>
        <ul className="flex flex-col gap-1">
          {sections.map((section, i) => (
            <li key={i} className="flex items-center gap-2">
              <span className="w-16 shrink-0 text-xs capitalize">
                {section.name}
              </span>
              <span
                className="h-2 rounded-full bg-primary"
                style={{
                  width: `${longest > 0 ? (section.durationSeconds / longest) * 100 : 0}%`,
                  minWidth: "0.5rem",
                }}
                aria-hidden
              />
              <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                {formatTime(section.durationSeconds)}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="flex items-center justify-between">
        <span className="text-xs text-muted-foreground">
          Uses ~{sections.length} {sections.length === 1 ? "credit" : "credits"}{" "}
          (1 per section)
        </span>
        <Button onClick={() => onStart(target)} disabled={sections.length === 0}>
          Start generation
        </Button>
      </div>
    </div>
  )
}
