import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import type { Playlist } from "@/lib/playlists"
import { cn } from "@/lib/utils"
import { ClipArtwork } from "@/components/song/ClipArtwork"

// Playlist cover (US-20.3). Custom upload wins; otherwise a mosaic of the first
// four songs' cover art (a glyph tile for a song without art, or past the end of a
// short playlist). An empty playlist shows a single glyph so it reads as "no songs
// yet" rather than a full cover.

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

  return (
    <div
      className={cn(box(className), "grid grid-cols-2 grid-rows-2 gap-px")}
      data-testid="playlist-mosaic"
      role="img"
      aria-label={`${playlist.name} cover`}
    >
      {Array.from({ length: 4 }, (_, i) => {
        const clipId = playlist.clipIds[i]
        return clipId ? (
          <ClipArtwork key={i} clipId={clipId} fallback={<Glyph size={18} />} />
        ) : (
          <Glyph key={i} size={18} />
        )
      })}
    </div>
  )
}
