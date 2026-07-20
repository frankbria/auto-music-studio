import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  FavouriteIcon,
  MusicNote01Icon,
  PlayIcon,
  Share01Icon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { versionLabel } from "@/lib/clip-labels"
import { formatTime } from "@/lib/clips"
import { cn } from "@/lib/utils"
import type { Clip } from "@/lib/workspace-clips"

// Presentational discovery card for the Explore page (US-20.1). Deliberately NOT
// the workspace ClipCard: this one is for anonymous browsing, so it has no owner
// actions (rename/publish/remix/drag/player dispatch) — the whole card is one
// link to the public song detail page. Artwork shows a music-note glyph: there
// is no authed artwork proxy, so a real <img src=.../artwork> would 401.

/** Compact engagement number: 8200 → "8.2K". */
const compact = new Intl.NumberFormat("en", { notation: "compact" })

function Stat({ icon, value }: { icon: typeof PlayIcon; value: number }) {
  return (
    <span className="flex items-center gap-0.5 tabular-nums">
      <HugeiconsIcon icon={icon} size={12} />
      {compact.format(value)}
    </span>
  )
}

export function ExploreClipCard({
  clip,
  rank,
}: {
  clip: Clip
  /** Chart position (1-based); when set, shows a ranking-number overlay (AC4). */
  rank?: number
}) {
  const version = versionLabel(clip.model)
  const styleText = clip.style_tags.join(", ")
  const hasStats =
    clip.play_count != null ||
    clip.like_count != null ||
    clip.share_count != null

  return (
    <Link
      href={`/song/${clip.id}`}
      data-testid="explore-clip-card"
      className="group/card flex w-40 shrink-0 flex-col gap-2 rounded-lg border border-border bg-card p-2 outline-none transition-colors hover:bg-accent/50 focus-visible:ring-3 focus-visible:ring-ring/50"
    >
      {/* Square artwork placeholder with duration + optional rank overlays. */}
      <div className="relative flex aspect-square items-center justify-center overflow-hidden rounded-md bg-muted text-muted-foreground">
        <HugeiconsIcon
          icon={MusicNote01Icon}
          size={28}
          className="group-hover/card:opacity-0"
        />
        <span className="absolute inset-0 flex items-center justify-center bg-background/30 opacity-0 transition-opacity group-hover/card:opacity-100">
          <HugeiconsIcon icon={PlayIcon} size={28} className="fill-current" />
        </span>
        {rank != null && (
          <span
            data-testid="clip-rank"
            className="absolute top-1 left-1 flex size-6 items-center justify-center rounded-md bg-background/85 text-sm font-bold tabular-nums"
          >
            {rank}
          </span>
        )}
        {clip.duration != null && (
          <span className="absolute right-1 bottom-1 rounded bg-background/80 px-1 text-[10px] tabular-nums">
            {formatTime(clip.duration)}
          </span>
        )}
      </div>

      <div className="flex min-w-0 flex-col gap-1">
        <span className="truncate text-sm font-medium" title={clip.title ?? undefined}>
          {clip.title ?? "Untitled clip"}
        </span>
        {styleText && (
          <p title={styleText} className="truncate text-xs text-muted-foreground">
            {styleText}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-1">
          {version && (
            <Badge variant="secondary" className="text-[10px]">
              {version}
            </Badge>
          )}
          {hasStats && (
            <div
              className={cn(
                "flex items-center gap-2 text-[10px] text-muted-foreground",
                version && "ml-auto"
              )}
            >
              {clip.play_count != null && (
                <Stat icon={PlayIcon} value={clip.play_count} />
              )}
              {clip.like_count != null && (
                <Stat icon={FavouriteIcon} value={clip.like_count} />
              )}
              {clip.share_count != null && (
                <Stat icon={Share01Icon} value={clip.share_count} />
              )}
            </div>
          )}
        </div>
      </div>
    </Link>
  )
}
