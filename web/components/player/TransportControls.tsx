"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  Loading03Icon,
  NextIcon,
  PauseIcon,
  PlayIcon,
  PreviousIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"

/** Previous / play-pause / next cluster. */
export function TransportControls() {
  const { state, dispatch } = usePlayer()
  const disabled = !state.current

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="icon"
        aria-label="Previous track"
        disabled={disabled}
        onClick={() => dispatch({ type: "previous" })}
      >
        <HugeiconsIcon icon={PreviousIcon} size={20} />
      </Button>

      <Button
        variant="default"
        size="icon"
        aria-label={state.isPlaying ? "Pause" : "Play"}
        aria-pressed={state.isPlaying}
        disabled={disabled}
        onClick={() => dispatch({ type: "toggle" })}
      >
        {state.isLoading ? (
          <HugeiconsIcon
            icon={Loading03Icon}
            size={20}
            className="animate-spin"
          />
        ) : (
          <HugeiconsIcon
            icon={state.isPlaying ? PauseIcon : PlayIcon}
            size={20}
          />
        )}
      </Button>

      <Button
        variant="ghost"
        size="icon"
        aria-label="Next track"
        disabled={disabled}
        onClick={() => dispatch({ type: "next" })}
      >
        <HugeiconsIcon icon={NextIcon} size={20} />
      </Button>
    </div>
  )
}
