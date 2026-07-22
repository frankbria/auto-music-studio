import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import type { Playlist } from "@/lib/playlists"
import { cn } from "@/lib/utils"

// Playlist cover (US-20.3). Custom upload wins; otherwise an auto-mosaic. There's
// no authed artwork proxy (a real <img src=.../artwork> would 401), so the mosaic
// is glyph tiles, not real thumbnails — swap a tile for the clip's artwork when a
// public artwork endpoint exists. An empty playlist shows a single glyph so it
// reads as "no songs yet" rather than a full cover.

function box(className?: string) {
  return cn("relative aspect-square w-full overflow-hidden rounded-md bg-muted", className)
}

function Glyph({ size }: { size: number }) {
  return (
    <span className="flex size-full items-center justify-center bg-muted text-muted-foreground">
      <HugeiconsIcon icon={MusicNote01Icon} size={size} aria-hidden />
    </span>
  )
}

export function PlaylistCover({
  playlist,
  className,
}: {
  playlist: Playlist
  className?: string
}) {
  if (playlist.coverDataUrl) {
    return (
      <div className={box(className)}>
        {/* eslint-disable-next-line @next/next/no-img-element -- object URL, not an optimizable asset */}
        <img
          src={playlist.coverDataUrl}
          alt={`${playlist.name} cover`}
          className="size-full object-cover"
        />
      </div>
    )
  }

  const count = playlist.clipIds.length

  if (count === 0) {
    return (
      <div className={box(className)} role="img" aria-label={`${playlist.name} cover`}>
        <Glyph size={28} />
      </div>
    )
  }

  // 2×2 glyph mosaic. Not thumbnails yet (see note above) — the grid is a stand-in
  // until real artwork lands.
  return (
    <div
      className={cn(box(className), "grid grid-cols-2 grid-rows-2 gap-px")}
      data-testid="playlist-mosaic"
      role="img"
      aria-label={`${playlist.name} cover`}
    >
      {Array.from({ length: 4 }, (_, i) => (
        <Glyph key={i} size={18} />
      ))}
    </div>
  )
}
