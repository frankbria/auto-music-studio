"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import { ClipArtwork } from "@/components/song/ClipArtwork"
import { usePlayer } from "@/contexts/player-context"

/** Current track thumbnail + title + artist. */
export function SongInfo() {
  const { state } = usePlayer()
  const track = state.current
  const glyph = (
    <HugeiconsIcon
      icon={MusicNote01Icon}
      size={20}
      className="text-muted-foreground"
    />
  )

  return (
    <div className="flex min-w-0 items-center gap-3">
      <div className="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted">
        {/* Keyed per track, so a failed load is retried whenever a track starts: a failure may be transient, or
            art may be added later. */}
        {track ? (
          <ClipArtwork key={track.id} clipId={track.id} fallback={glyph} />
        ) : (
          glyph
        )}
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-medium text-foreground">
          {track?.title ?? "Nothing playing"}
        </p>
        <p className="truncate text-xs text-muted-foreground">
          {track?.artist ?? "—"}
        </p>
      </div>
    </div>
  )
}
