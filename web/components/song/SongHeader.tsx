"use client"

import { useMemo, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  FavouriteIcon,
  GlobeIcon,
  Share01Icon,
  ThumbsDownIcon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { usePlayer } from "@/contexts/player-context"
import { modeLabel, versionLabel } from "@/lib/clip-labels"
import { cn } from "@/lib/utils"
import type { Clip } from "@/lib/workspace-clips"

// Song-detail header (US-17.1): title, artist, style/version/mode badges, and
// the inline Like / Dislike / Share / Publish controls. Like is wired to the
// global player store (the one backend-free action with a real home, as in
// ClipCard); dislike/share/publish have no backend yet, so they give local
// optimistic feedback and emit callbacks the parent wires when routes land
// (US-17.6). Matches ClipCard's behavior so actions read the same app-wide.

export type SongHeaderProps = {
  clip: Clip
  onDislike?: (id: string) => void
  onShare?: (id: string) => void
  onPublishToggle?: (id: string, next: boolean) => void
}

export function SongHeader({
  clip,
  onDislike,
  onShare,
  onPublishToggle,
}: SongHeaderProps) {
  const { state, dispatch } = usePlayer()
  const likedSet = useMemo(() => new Set(state.likedIds), [state.likedIds])
  const liked = likedSet.has(clip.id)
  const [disliked, setDisliked] = useState(false)
  const [optimisticPublic, setOptimisticPublic] = useState<boolean | null>(null)
  const isPublic = optimisticPublic ?? clip.is_public

  const version = versionLabel(clip.model)
  const mode = modeLabel(clip.generation_mode)

  function dislike() {
    setDisliked((d) => !d)
    onDislike?.(clip.id)
  }

  function togglePublish() {
    const next = !isPublic
    onPublishToggle?.(clip.id, next)
    if (onPublishToggle) setOptimisticPublic(next)
  }

  return (
    <header className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h1 className="text-2xl font-bold tracking-tight">
          {clip.title ?? "Untitled clip"}
        </h1>
        {/* Backend ClipResponse has no artist column yet — placeholder. */}
        <p className="text-sm text-muted-foreground">Unknown artist</p>
      </div>

      {(version || mode || clip.style_tags.length > 0) && (
        <div className="flex flex-wrap items-center gap-1">
          {version && <Badge variant="secondary">{version}</Badge>}
          {mode && <Badge variant="outline">{mode}</Badge>}
          {clip.style_tags.map((tag) => (
            <Badge key={tag} variant="outline">
              {tag}
            </Badge>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-1">
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={liked ? "Unlike" : "Like"}
          aria-pressed={liked}
          onClick={() => dispatch({ type: "like/toggle", id: clip.id })}
          className={cn(liked && "text-primary")}
        >
          <HugeiconsIcon
            icon={FavouriteIcon}
            size={18}
            className={cn(liked && "fill-current")}
          />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Dislike"
          aria-pressed={disliked}
          onClick={dislike}
          className={cn(disliked && "text-primary")}
        >
          <HugeiconsIcon icon={ThumbsDownIcon} size={18} />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label="Share"
          onClick={() => onShare?.(clip.id)}
        >
          <HugeiconsIcon icon={Share01Icon} size={18} />
        </Button>
        <Button
          variant="ghost"
          size="icon-sm"
          aria-label={isPublic ? "Unpublish (make private)" : "Publish (make public)"}
          aria-pressed={isPublic}
          onClick={togglePublish}
          className={cn(isPublic && "text-primary")}
        >
          <HugeiconsIcon icon={GlobeIcon} size={18} />
        </Button>
      </div>
    </header>
  )
}
