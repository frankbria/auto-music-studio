"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  FitToScreenIcon,
  ZoomInAreaIcon,
  ZoomOutAreaIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"

// Zoom toolbar for the waveform editor (US-18.1). Buttons are one of the three
// zoom affordances (the others are Ctrl+wheel and pinch, handled on the canvas).
// "Fit" resets to the full-clip overview. atMin/atMax disable the buttons at the
// zoom boundaries so the control reflects what's actually possible.

export function ZoomControls({
  onZoomIn,
  onZoomOut,
  onFit,
  atMin,
  atMax,
}: {
  onZoomIn: () => void
  onZoomOut: () => void
  onFit: () => void
  atMin: boolean
  atMax: boolean
}) {
  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Zoom out"
        onClick={onZoomOut}
        disabled={atMin}
      >
        <HugeiconsIcon icon={ZoomOutAreaIcon} />
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Zoom in"
        onClick={onZoomIn}
        disabled={atMax}
      >
        <HugeiconsIcon icon={ZoomInAreaIcon} />
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Fit to view"
        onClick={onFit}
        disabled={atMin}
      >
        <HugeiconsIcon icon={FitToScreenIcon} />
      </Button>
    </div>
  )
}
