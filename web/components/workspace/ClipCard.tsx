"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import { formatTime } from "@/lib/clips"
import type { Clip } from "@/lib/workspace-clips"

// ponytail: minimal list-view card. US-16.6 extends it with inline title edit,
// play/like/menu action buttons, and full interactivity — out of scope here.

/** Minimal clip card: thumbnail placeholder + duration, title, and style tags. */
export function ClipCard({ clip }: { clip: Clip }) {
  return (
    <div
      data-testid="clip-card"
      className="flex gap-3 rounded-lg border border-border bg-card p-2"
    >
      <div className="relative flex size-14 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
        <HugeiconsIcon icon={MusicNote01Icon} size={20} />
        {clip.duration != null && (
          <span className="absolute right-0.5 bottom-0.5 rounded bg-background/80 px-1 text-[10px] tabular-nums">
            {formatTime(clip.duration)}
          </span>
        )}
      </div>
      <div className="flex min-w-0 flex-col justify-center">
        <p className="truncate text-sm font-medium">
          {clip.title ?? "Untitled clip"}
        </p>
        {clip.style_tags.length > 0 && (
          <p className="truncate text-xs text-muted-foreground">
            {clip.style_tags.join(", ")}
          </p>
        )}
      </div>
    </div>
  )
}
