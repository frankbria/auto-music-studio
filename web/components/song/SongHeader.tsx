"use client"

import { useState, type ReactNode } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  FavouriteIcon,
  MusicNote01Icon,
  Share01Icon,
  ThumbsDownIcon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { ClipArtwork } from "@/components/song/ClipArtwork"
import { ReportClipButton } from "@/components/moderation/ReportClipButton"
import { ShareModal } from "@/components/song/ShareModal"
import { VisibilityBadge } from "@/components/song/VisibilityBadge"
import { VisibilityToggle } from "@/components/song/VisibilityToggle"
import { usePlayer } from "@/contexts/player-context"
import { useLikeToggle } from "@/hooks/use-like-toggle"
import { modeLabel, versionLabel } from "@/lib/clip-labels"
import { cn } from "@/lib/utils"
import { visibilityOf, type Clip, type Visibility } from "@/lib/workspace-clips"

// Song-detail header (US-17.1 / US-17.6, tri-state in US-20.7): title, artist,
// style/version/mode/visibility badges, and the inline Like / Dislike / Share /
// Visibility controls. Like and Dislike are wired to the global player store
// (persisted in localStorage, so they survive a reload — as in ClipCard). Share
// opens the ShareModal. The visibility picker is prop-driven: SongDetail passes
// the persisted `visibility` + an `onVisibilityChange` that hits the API with a
// guard (only reachable going "public"); standalone it falls back to a local
// optimistic toggle. `onDislike`/`onShare` remain optional observers.

export type SongHeaderProps = {
  clip: Clip
  onDislike?: (id: string) => void
  onShare?: (id: string) => void
  onVisibilityChange?: (id: string, next: Visibility) => void
  /**
   * Controlled visibility. When the parent owns visibility state (US-17.2's
   * action menu shares it), this wins over the local optimistic toggle.
   */
  visibility?: Visibility
  /**
   * Whether the viewer owns this clip (US-20.0). Only the owner may change
   * visibility, so the Publish toggle is hidden otherwise. Defaults to **false**:
   * this header renders on a public page now, so an omitted prop must fail
   * closed (toggle hidden) rather than offer a stranger a control that would
   * only 404 anyway.
   */
  isOwner?: boolean
  /** Extra controls rendered at the end of the action row (e.g. the menu). */
  actions?: ReactNode
}

export function SongHeader({
  clip,
  onDislike,
  onShare,
  onVisibilityChange,
  visibility: visibilityProp,
  isOwner = false,
  actions,
}: SongHeaderProps) {
  const [optimisticVisibility, setOptimisticVisibility] =
    useState<Visibility | null>(null)
  const [shareOpen, setShareOpen] = useState(false)
  const visibility =
    visibilityProp ?? optimisticVisibility ?? visibilityOf(clip)

  const version = versionLabel(clip.model)
  const mode = modeLabel(clip.generation_mode)

  function share() {
    setShareOpen(true)
    onShare?.(clip.id)
  }

  function changeVisibility(next: Visibility) {
    onVisibilityChange?.(clip.id, next)
    // When wired via SongDetail, `visibility` is controlled by useSongActions
    // (which persists + guards + rolls back), so this local flip is shadowed and
    // the hook owns the visible state. It only takes effect for a standalone,
    // uncontrolled SongHeader (no visibility prop) as immediate local feedback.
    setOptimisticVisibility(next)
  }

  return (
    <header className="flex flex-col gap-6 sm:flex-row sm:items-end">
      <div
        data-testid="song-hero-art"
        className="flex size-40 shrink-0 items-center justify-center overflow-hidden rounded-2xl bg-muted text-muted-foreground sm:size-52"
      >
        <ClipArtwork
          clipId={clip.id}
          fallback={
            <HugeiconsIcon icon={MusicNote01Icon} size={48} aria-hidden />
          }
        />
      </div>
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
            {clip.title ?? "Untitled clip"}
          </h1>
          <p className="text-sm text-muted-foreground">
            {clip.artist || "Unknown artist"}
          </p>
        </div>

        <SongBadges
          clip={clip}
          version={version}
          mode={mode}
          visibility={isOwner ? visibility : null}
        />

        <div className="flex flex-wrap items-center gap-1">
          <ReactionButtons clipId={clip.id} onDislike={onDislike} />
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Share"
            onClick={share}
          >
            <HugeiconsIcon icon={Share01Icon} size={18} />
          </Button>
          <ReportClipButton clipId={clip.id} isOwner={isOwner} />
          {isOwner && (
            <VisibilityToggle value={visibility} onChange={changeVisibility} />
          )}
          {actions && <div className="ml-auto">{actions}</div>}
        </div>

        <ShareModal
          open={shareOpen}
          clipId={clip.id}
          clipTitle={clip.title}
          onClose={() => setShareOpen(false)}
        />
      </div>
    </header>
  )
}

/** Content warning, model version, mode, style tags, and the owner's visibility. */
function SongBadges({
  clip,
  version,
  mode,
  visibility,
}: {
  clip: Clip
  version: string | null
  mode: string | null
  /** The owner's visibility badge; null for anyone else. */
  visibility: Visibility | null
}) {
  return (
    <div className="flex flex-wrap items-center gap-1">
      {clip.content_warning && (
        <Badge variant="destructive">Content warning</Badge>
      )}
      {version && <Badge variant="secondary">{version}</Badge>}
      {mode && <Badge variant="outline">{mode}</Badge>}
      {clip.style_tags.map((tag) => (
        <Badge key={tag} variant="outline">
          {tag}
        </Badge>
      ))}
      {visibility && <VisibilityBadge visibility={visibility} />}
    </div>
  )
}

/** Like and Dislike, wired to the player store (persisted, as in ClipCard). */
function ReactionButtons({
  clipId,
  onDislike,
}: {
  clipId: string
  onDislike?: (id: string) => void
}) {
  const { state, dispatch } = usePlayer()
  const toggleLike = useLikeToggle()
  const liked = state.likedIds.includes(clipId)
  const disliked = state.dislikedIds.includes(clipId)

  function dislike() {
    dispatch({ type: "dislike/toggle", id: clipId })
    onDislike?.(clipId)
  }

  return (
    <>
      <Button
        variant="ghost"
        size="icon-sm"
        aria-label={liked ? "Unlike" : "Like"}
        aria-pressed={liked}
        onClick={() => toggleLike(clipId)}
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
    </>
  )
}
