import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import { coverClips, type Playlist } from "@/lib/playlists"
import { cn } from "@/lib/utils"
import type { Clip } from "@/lib/workspace-clips"

// Playlist cover (US-20.3). Custom upload wins; otherwise an auto-mosaic of the
// first up-to-4 songs. There's no authed artwork proxy (real <img src=.../artwork>
// would 401), so each mosaic tile is a music-note glyph, not a real thumbnail —
// swap the tile for the clip's artwork when a public artwork endpoint exists.

/** One glyph tile of the mosaic. */
function Tile({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "flex items-center justify-center bg-muted text-muted-foreground",
        className
      )}
    >
      <HugeiconsIcon icon={MusicNote01Icon} size={20} aria-hidden />
    </span>
  )
}

export function PlaylistCover({
  playlist,
  clips,
  className,
}: {
  playlist: Playlist
  /** Resolved cover clips; defaults to the playlist's first 4 songs. */
  clips?: Clip[]
  className?: string
}) {
  const tiles = clips ?? coverClips(playlist)

  const box = cn(
    "relative aspect-square w-full overflow-hidden rounded-md bg-muted",
    className
  )

  if (playlist.coverDataUrl) {
    return (
      <div className={box}>
        {/* eslint-disable-next-line @next/next/no-img-element -- object URL, not an optimizable asset */}
        <img
          src={playlist.coverDataUrl}
          alt={`${playlist.name} cover`}
          className="size-full object-cover"
        />
      </div>
    )
  }

  // 2×2 grid; fewer than 4 songs → fill remaining slots with plain glyph tiles so
  // the cover is always a full square (1 song still reads as a cover, not a crop).
  const slots = Array.from({ length: 4 }, (_, i) => tiles[i] ?? null)

  return (
    <div
      className={cn(box, "grid grid-cols-2 grid-rows-2 gap-px")}
      data-testid="playlist-mosaic"
      role="img"
      aria-label={`${playlist.name} cover`}
    >
      {slots.map((clip, i) => (
        <Tile key={clip?.id ?? `empty-${i}`} />
      ))}
    </div>
  )
}
