"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  VolumeHighIcon,
  VolumeLowIcon,
  VolumeMuteIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"

/** Mute toggle + volume slider. */
export function VolumeControl() {
  const { state, dispatch } = usePlayer()
  const effective = state.isMuted ? 0 : state.volume
  const icon =
    effective === 0
      ? VolumeMuteIcon
      : effective < 0.5
        ? VolumeLowIcon
        : VolumeHighIcon

  return (
    <div className="flex items-center gap-1">
      <Button
        variant="ghost"
        size="icon"
        aria-label={state.isMuted ? "Unmute" : "Mute"}
        aria-pressed={state.isMuted}
        onClick={() => dispatch({ type: "mute/toggle" })}
      >
        <HugeiconsIcon icon={icon} size={18} />
      </Button>
      <input
        type="range"
        aria-label="Volume"
        min={0}
        max={1}
        step={0.01}
        value={effective}
        onChange={(e) =>
          dispatch({ type: "volume/set", volume: Number(e.target.value) })
        }
        className="h-1 w-20 cursor-pointer appearance-none rounded-full bg-muted accent-primary"
      />
    </div>
  )
}
