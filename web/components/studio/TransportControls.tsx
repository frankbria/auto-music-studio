"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  PauseIcon,
  PlayIcon,
  PreviousIcon,
  RepeatIcon,
  StopIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { useStudio } from "@/contexts/studio-context"

/** Return-to-start / play-pause / stop cluster for the Studio transport
 * (US-19.1). Return-to-start rewinds without touching play state (so it can
 * rewind mid-playback); Stop rewinds AND pauses, the DAW convention. */
export function TransportControls() {
  const { state, dispatch } = useStudio()

  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Return to start"
        // SEEK (not SET_PLAYHEAD) so a rewind mid-playback actually
        // reschedules audio from 0 instead of getting stomped by the rAF
        // loop's stale origin on the next frame.
        onClick={() => dispatch({ type: "SEEK", sec: 0 })}
      >
        <HugeiconsIcon icon={PreviousIcon} size={20} />
      </Button>

      <Button
        type="button"
        variant="default"
        size="icon"
        aria-label={state.isPlaying ? "Pause" : "Play"}
        aria-pressed={state.isPlaying}
        onClick={() =>
          dispatch({ type: "SET_PLAYING", playing: !state.isPlaying })
        }
      >
        <HugeiconsIcon
          icon={state.isPlaying ? PauseIcon : PlayIcon}
          size={20}
        />
      </Button>

      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Stop"
        onClick={() => {
          dispatch({ type: "SET_PLAYING", playing: false })
          dispatch({ type: "SET_PLAYHEAD", sec: 0 })
        }}
      >
        <HugeiconsIcon icon={StopIcon} size={20} />
      </Button>

      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label="Toggle loop"
        aria-pressed={state.loopEnabled}
        className={state.loopEnabled ? "text-primary" : undefined}
        onClick={() => dispatch({ type: "TOGGLE_LOOP" })}
      >
        <HugeiconsIcon icon={RepeatIcon} size={20} />
      </Button>
    </div>
  )
}
