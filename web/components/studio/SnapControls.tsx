"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Magnet01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { useStudio } from "@/contexts/studio-context"
import type { SnapResolution } from "@/lib/timeline"

const RESOLUTIONS: { value: SnapResolution; label: string }[] = [
  { value: "1bar", label: "1 bar" },
  { value: "1beat", label: "1 beat" },
  { value: "1/2beat", label: "1/2 beat" },
  { value: "1/4beat", label: "1/4 beat" },
]

/** Snap-to-grid toggle + grid resolution picker for the studio toolbar
 * (US-19.3). */
export function SnapControls() {
  const { state, dispatch } = useStudio()
  const current = RESOLUTIONS.find((r) => r.value === state.snapResolution)
  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="sm"
        aria-label="Snap to grid"
        aria-pressed={state.snapEnabled}
        className={state.snapEnabled ? "bg-accent" : undefined}
        onClick={() => dispatch({ type: "TOGGLE_SNAP" })}
      >
        <HugeiconsIcon icon={Magnet01Icon} data-icon="inline-start" />
        Snap
      </Button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            aria-label="Snap resolution"
          >
            {current?.label}
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {RESOLUTIONS.map((r) => (
            <DropdownMenuItem
              key={r.value}
              onSelect={() =>
                dispatch({ type: "SET_SNAP_RESOLUTION", resolution: r.value })
              }
            >
              {r.label}
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
