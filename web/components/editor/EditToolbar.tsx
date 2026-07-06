"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Slider } from "@/components/ui/slider"

// Audio-processing toolbar for the waveform editor (US-18.3). Sits above the
// waveform and applies the pure transforms in lib/waveform-edit.ts to the
// current selection (or, for normalize, the whole clip when nothing is
// selected). Edits are non-destructive — the parent holds them in state.
//
// Region ops (fade / gain / silence) need a selection, so they disable without
// one. Normalize falls back to the whole clip; crossfade acts at the playhead.
// Gain previews live: the slider reports each value up via onGainPreview so the
// parent can show the pending change on the waveform before Apply commits it.

const GAIN_MIN_DB = -24
const GAIN_MAX_DB = 24
const CROSSFADE_MIN_MS = 10
const CROSSFADE_MAX_MS = 500
const CROSSFADE_DEFAULT_MS = 100

export type EditToolbarProps = {
  hasSelection: boolean
  onFadeIn: () => void
  onFadeOut: () => void
  onSilence: () => void
  onNormalize: () => void
  /** Live visual preview of a pending gain; null clears it (cancel/close). */
  onGainPreview: (gainDb: number | null) => void
  onGainApply: (gainDb: number) => void
  onCrossfade: (durationSec: number) => void
}

export function EditToolbar({
  hasSelection,
  onFadeIn,
  onFadeOut,
  onSilence,
  onNormalize,
  onGainPreview,
  onGainApply,
  onCrossfade,
}: EditToolbarProps) {
  const [gainDb, setGainDb] = useState(0)
  const [crossfadeMs, setCrossfadeMs] = useState(CROSSFADE_DEFAULT_MS)
  const [gainOpen, setGainOpen] = useState(false)
  const [crossfadeOpen, setCrossfadeOpen] = useState(false)

  // Reset + drop any live preview whenever the gain popover closes; commit only
  // happens through Apply. Opening starts from a clean 0 dB. Controlled so Apply
  // can close it (else a second Apply would fire on a now-cleared selection).
  const onGainOpenChange = (open: boolean) => {
    setGainOpen(open)
    if (open) {
      setGainDb(0)
      onGainPreview(0)
    } else {
      onGainPreview(null)
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1" data-testid="edit-toolbar">
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onFadeIn}
        disabled={!hasSelection}
      >
        Fade In
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onFadeOut}
        disabled={!hasSelection}
      >
        Fade Out
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={onSilence}
        disabled={!hasSelection}
      >
        Silence
      </Button>
      <Button type="button" variant="outline" size="sm" onClick={onNormalize}>
        Normalize
      </Button>

      <Popover open={gainOpen} onOpenChange={onGainOpenChange}>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={!hasSelection}
          >
            Gain
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-64 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">Gain</span>
            <span className="text-muted-foreground tabular-nums">
              {gainDb > 0 ? "+" : ""}
              {gainDb.toFixed(1)} dB
            </span>
          </div>
          <Slider
            aria-label="Gain in decibels"
            min={GAIN_MIN_DB}
            max={GAIN_MAX_DB}
            step={0.5}
            value={[gainDb]}
            onValueChange={([v]) => {
              setGainDb(v)
              onGainPreview(v)
            }}
          />
          <Button
            type="button"
            size="sm"
            className="w-full"
            aria-label="Apply gain"
            onClick={() => {
              onGainApply(gainDb)
              onGainPreview(null) // controlled close won't fire onOpenChange
              setGainOpen(false)
            }}
          >
            Apply
          </Button>
        </PopoverContent>
      </Popover>

      <Popover open={crossfadeOpen} onOpenChange={setCrossfadeOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="outline" size="sm">
            Crossfade
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-64 space-y-3">
          <div className="flex items-center justify-between text-sm">
            <span className="font-medium">Crossfade at playhead</span>
            <span className="text-muted-foreground tabular-nums">
              {crossfadeMs} ms
            </span>
          </div>
          <Slider
            aria-label="Crossfade duration in milliseconds"
            min={CROSSFADE_MIN_MS}
            max={CROSSFADE_MAX_MS}
            step={10}
            value={[crossfadeMs]}
            onValueChange={([v]) => setCrossfadeMs(v)}
          />
          <Button
            type="button"
            size="sm"
            className="w-full"
            aria-label="Apply crossfade"
            onClick={() => {
              onCrossfade(crossfadeMs / 1000)
              setCrossfadeOpen(false)
            }}
          >
            Apply
          </Button>
        </PopoverContent>
      </Popover>
    </div>
  )
}
