"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import { usePlayer } from "@/contexts/player-context"

/**
 * Current track thumbnail + title + artist. ponytail: not yet a link — the
 * `/song/[id]` detail route doesn't exist; wrap in next/link when it lands.
 */
export function SongInfo() {
  const { state } = usePlayer()
  const track = state.current
  // Whether the current track's art failed (404 = no cover art). Reset during render whenever
  // a track starts, so a transient failure or art added later is retried on the next play.
  const [failed, setFailed] = useState(false)
  const [shownTrack, setShownTrack] = useState(track)
  if (track !== shownTrack) {
    setShownTrack(track)
    setFailed(false)
  }
  const artworkUrl = !failed ? track?.artworkUrl : undefined

  return (
    <div className="flex min-w-0 items-center gap-3">
      <div className="flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted">
        {artworkUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- artwork is a dynamic proxied stream, not a build-time asset
          <img
            src={artworkUrl}
            alt=""
            onError={() => setFailed(true)}
            className="size-full object-cover"
          />
        ) : (
          <HugeiconsIcon
            icon={MusicNote01Icon}
            size={20}
            className="text-muted-foreground"
          />
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
