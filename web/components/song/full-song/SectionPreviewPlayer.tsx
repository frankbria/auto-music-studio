"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { PauseIcon, PlayIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"
import { formatTime, trackFromClip } from "@/lib/clips"

// Preview control for a generated section / the finished song (US-17.4). Reuses
// the global player store (like SongPlayer/ClipCard) so playback flows through
// the single shared audio engine and the persistent Playbar keeps working — the
// wizard just needs a play/pause remote for a clip it doesn't have a full Clip
// object for (only the id from the completed extend job).

export function SectionPreviewPlayer({
  clipId,
  title,
  durationSeconds,
}: {
  clipId: string
  title: string
  durationSeconds: number
}) {
  const { state, dispatch } = usePlayer()
  const isCurrent = state.current?.id === clipId
  const isPlaying = isCurrent && state.isPlaying

  function toggle() {
    if (isCurrent) {
      dispatch({ type: "toggle" })
    } else {
      dispatch({
        type: "play/track",
        track: trackFromClip({ id: clipId, title, duration: durationSeconds }),
      })
    }
  }

  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/40 p-3">
      <Button
        size="icon"
        aria-label={isPlaying ? "Pause preview" : "Play preview"}
        aria-pressed={isPlaying}
        onClick={toggle}
        className="size-10 shrink-0 rounded-full"
      >
        <HugeiconsIcon
          icon={isPlaying ? PauseIcon : PlayIcon}
          size={20}
          className="fill-current"
        />
      </Button>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{title}</p>
        <p className="text-xs tabular-nums text-muted-foreground">
          {formatTime(durationSeconds)}
        </p>
      </div>
    </div>
  )
}
