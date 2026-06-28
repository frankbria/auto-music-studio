"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { PauseIcon, PlayIcon } from "@hugeicons/core-free-icons"

import { SongWaveform } from "@/components/song/SongWaveform"
import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"
import { formatTime, trackFromClip } from "@/lib/clips"
import type { Clip } from "@/lib/workspace-clips"

// Song-detail player (US-17.1): a large play/pause control wired to the global
// player store, the seekable SongWaveform, and a time readout. Reusing the
// global player means the persistent Playbar, queue, and keyboard shortcuts all
// keep working — this is just a bigger remote for the same engine.

export function SongPlayer({ clip }: { clip: Clip }) {
  const { state, dispatch } = usePlayer()
  const isCurrent = state.current?.id === clip.id
  const isPlaying = isCurrent && state.isPlaying

  function toggle() {
    if (isCurrent) {
      dispatch({ type: "toggle" })
    } else {
      dispatch({ type: "play/track", track: trackFromClip(clip) })
    }
  }

  // Before this clip is the active track, show its own stored duration; once
  // playing, the audio engine's live duration takes over.
  const duration = isCurrent ? state.duration : (clip.duration ?? 0)
  const currentTime = isCurrent ? state.currentTime : 0

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
      <div className="flex items-center gap-4">
        <Button
          size="icon"
          aria-label={isPlaying ? "Pause" : "Play"}
          aria-pressed={isPlaying}
          onClick={toggle}
          className="size-12 shrink-0 rounded-full"
        >
          <HugeiconsIcon
            icon={isPlaying ? PauseIcon : PlayIcon}
            size={24}
            className="fill-current"
          />
        </Button>
        <div className="min-w-0 flex-1">
          <SongWaveform clipId={clip.id} />
        </div>
      </div>
      <div className="flex justify-between text-xs tabular-nums text-muted-foreground">
        <span>{formatTime(currentTime)}</span>
        <span>{formatTime(duration)}</span>
      </div>
    </div>
  )
}
