"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { formatTime } from "@/lib/clips"
import type { Clip } from "@/lib/workspace-clips"

/**
 * Selected-song summary for the release page header (US-21.1). Shows the chosen
 * clip's thumbnail, title, duration, and its mastering/distribution status, plus
 * a "Change Song" affordance to reopen the selector.
 *
 * ponytail: no artwork proxy exists in web/ (thumbnails are music-glyph
 * placeholders everywhere), and distribution has no releases API yet — the
 * Distribute workflow lands in US-21.4/21.5, so distribution status is a static
 * "Not distributed" until then.
 */
export function SelectedSongSummary({
  clip,
  onChangeSong,
}: {
  clip: Clip
  onChangeSong: () => void
}) {
  // Mastering status is derived from generation_mode per the story plan. No clip
  // carries "mastered" until the mastering workflow (US-21.2) produces one, so
  // this reads "Not mastered" for every clip today — correct, not a bug.
  const mastered = clip.generation_mode === "mastered"

  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-4">
        <span className="flex size-16 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
          <HugeiconsIcon icon={MusicNote01Icon} size={24} />
        </span>

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <h2 className="truncate text-lg font-semibold">
            {clip.title ?? "Untitled"}
          </h2>
          <p className="text-sm text-muted-foreground tabular-nums">
            {formatTime(clip.duration ?? 0)}
          </p>
          <div className="flex flex-wrap items-center gap-1 pt-1">
            <Badge variant={mastered ? "default" : "secondary"}>
              {mastered ? "Mastered" : "Not mastered"}
            </Badge>
            <Badge variant="outline">Not distributed</Badge>
          </div>
        </div>

        <Button variant="outline" size="sm" onClick={onChangeSong}>
          Change Song
        </Button>
      </CardContent>
    </Card>
  )
}
