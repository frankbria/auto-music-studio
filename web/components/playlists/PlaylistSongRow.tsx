"use client"

import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  ArrowDown01Icon,
  ArrowUp01Icon,
  Cancel01Icon,
  DragDropVerticalIcon,
  MusicNote01Icon,
  PlayIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { versionLabel } from "@/lib/clip-labels"
import { formatTime } from "@/lib/clips"
import type { Clip } from "@/lib/workspace-clips"

// One song in the playlist detail list (US-20.3). Play affordance links to the
// public song page (playback controls live there — no authed artwork/stream proxy
// to embed here). Reorder is keyboard-accessible via up/down buttons; native HTML5
// drag (handled by the parent) is the pointer path for the "drag-to-reorder" AC.

export function PlaylistSongRow({
  clip,
  index,
  total,
  onMoveUp,
  onMoveDown,
  onRemove,
  dragProps,
  dragging,
}: {
  clip: Clip
  index: number
  total: number
  onMoveUp: () => void
  onMoveDown: () => void
  onRemove: () => void
  /** Native drag handlers wired by the parent (PlaylistDetail). */
  dragProps: React.HTMLAttributes<HTMLDivElement> & { draggable: boolean }
  dragging: boolean
}) {
  const version = versionLabel(clip.model)
  const styleText = clip.style_tags.join(", ")

  return (
    <div
      {...dragProps}
      data-testid="playlist-song-row"
      className={`flex items-center gap-3 rounded-md border border-transparent p-2 hover:bg-accent/50 ${
        dragging ? "opacity-40" : ""
      }`}
    >
      <span
        aria-hidden
        className="cursor-grab text-muted-foreground active:cursor-grabbing"
        title="Drag to reorder"
      >
        <HugeiconsIcon icon={DragDropVerticalIcon} size={16} />
      </span>

      <Link
        href={`/song/${clip.id}`}
        aria-label={`Play ${clip.title ?? "Untitled clip"}`}
        className="group/play relative flex size-11 shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <HugeiconsIcon
          icon={MusicNote01Icon}
          size={18}
          aria-hidden
          className="group-hover/play:opacity-0"
        />
        <span className="absolute inset-0 flex items-center justify-center bg-background/30 opacity-0 transition-opacity group-hover/play:opacity-100">
          <HugeiconsIcon icon={PlayIcon} size={18} className="fill-current" />
        </span>
      </Link>

      <div className="flex min-w-0 flex-1 flex-col">
        <Link
          href={`/song/${clip.id}`}
          className="truncate text-sm font-medium hover:underline"
          title={clip.title ?? undefined}
        >
          {clip.title ?? "Untitled clip"}
        </Link>
        {styleText && (
          <span className="truncate text-xs text-muted-foreground" title={styleText}>
            {styleText}
          </span>
        )}
      </div>

      <div className="hidden items-center gap-3 text-xs text-muted-foreground sm:flex">
        {version && <span>{version}</span>}
        {clip.duration != null && (
          <span className="tabular-nums">{formatTime(clip.duration)}</span>
        )}
      </div>

      <div className="flex items-center gap-0.5">
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          onClick={onMoveUp}
          disabled={index === 0}
          aria-label="Move up"
        >
          <HugeiconsIcon icon={ArrowUp01Icon} size={16} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-8"
          onClick={onMoveDown}
          disabled={index === total - 1}
          aria-label="Move down"
        >
          <HugeiconsIcon icon={ArrowDown01Icon} size={16} />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="size-8 text-muted-foreground hover:text-destructive"
          onClick={onRemove}
          aria-label={`Remove ${clip.title ?? "song"} from playlist`}
        >
          <HugeiconsIcon icon={Cancel01Icon} size={16} />
        </Button>
      </div>
    </div>
  )
}
