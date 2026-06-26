"use client"

import { usePlayer } from "@/contexts/player-context"
import { formatTime } from "@/lib/clips"

/** Seek bar with current / total time. Click or drag commits live seeks. */
export function ProgressScrubber() {
  const { state, dispatch } = usePlayer()
  const max = state.duration > 0 ? state.duration : 0

  return (
    <div className="flex w-full items-center gap-2">
      <span className="w-10 text-right text-xs text-muted-foreground tabular-nums">
        {formatTime(state.currentTime)}
      </span>
      <input
        type="range"
        aria-label="Seek"
        min={0}
        max={max || 1}
        step={0.1}
        value={Math.min(state.currentTime, max || 1)}
        disabled={!state.current}
        onChange={(e) =>
          dispatch({ type: "seek/request", time: Number(e.target.value) })
        }
        className="h-1 flex-1 cursor-pointer appearance-none rounded-full bg-muted accent-primary disabled:cursor-not-allowed disabled:opacity-50"
      />
      <span className="w-10 text-xs text-muted-foreground tabular-nums">
        {formatTime(state.duration)}
      </span>
    </div>
  )
}
