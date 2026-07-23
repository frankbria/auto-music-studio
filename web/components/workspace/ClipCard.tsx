"use client"

import { useMemo, useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  ArrowDown01Icon,
  Delete02Icon,
  Edit02Icon,
  FavouriteIcon,
  LockIcon,
  MoreHorizontalIcon,
  MusicNote01Icon,
  PlayIcon,
  Share01Icon,
  ThumbsDownIcon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { DeleteSongDialog } from "@/components/song/DeleteSongDialog"
import { PublishGuardPrompt } from "@/components/song/PublishGuardPrompt"
import { ShareModal } from "@/components/song/ShareModal"
import { SongActionModal } from "@/components/song/SongActionModal"
import { VisibilityBadge } from "@/components/song/VisibilityBadge"
import { VisibilityToggle } from "@/components/song/VisibilityToggle"
import { usePlayer } from "@/contexts/player-context"
import { useSongActions } from "@/hooks/use-song-actions"
import { setClipDragData, setDragTrackType } from "@/lib/clip-drag"
import { inferTrackType } from "@/lib/track-types"
import { modeLabel, versionLabel } from "@/lib/clip-labels"
import { formatTime, trackFromClip } from "@/lib/clips"
import { isFullSongEligible } from "@/lib/song-structure"
import { cn } from "@/lib/utils"
import type { Clip, Visibility } from "@/lib/workspace-clips"

// US-16.6 / US-17.5 / US-17.6: the reusable clip card. Play, Like and Dislike are
// wired to the global player store (Like/Dislike persist in localStorage). Share
// opens the ShareModal; the visibility picker (US-20.7, née the two-state Publish
// toggle) persists through useSongActions (guarded — needs a title + a style tag
// to go public; private/unlisted are ungated). The ⋯ menu and Remix CTA also
// dispatch through useSongActions (US-17.5) — the same registry-driven seam the
// song-detail menu uses — so any action opens its modal, navigates, downloads,
// changes visibility, or confirms a delete wherever a card is rendered.
// `onDislike`/`onShare`/`onVisibilityChange` remain optional observers for
// parent analytics/refetch.
// The action vocabulary lives in lib/song-actions (US-17.2) and is re-exported
// here so existing imports keep working. The card is also a native HTML5 drag
// source (US-19.1): dragging it onto a Studio track lane carries an "add"
// payload (lib/clip-drag.ts) that the lane's drop handler turns into an
// ADD_CLIP placement.

export type { ClipMenuAction } from "@/lib/song-actions"
import type { ClipMenuAction, SongActionId } from "@/lib/song-actions"

export type ClipCardProps = {
  clip: Clip
  /** Inline-rename committed (blur/Enter). */
  onTitleChange?: (id: string, title: string) => void
  /**
   * Observer for menu selections (analytics / parent refetch). The action is
   * also dispatched internally through useSongActions — this fires alongside it.
   */
  onMenuAction?: (action: ClipMenuAction, clipId: string) => void
  onGetFullSong?: (id: string) => void
  onDislike?: (id: string) => void
  onShare?: (id: string) => void
  /** Visibility picker (US-20.7); `next` is the requested tri-state value. */
  onVisibilityChange?: (id: string, next: Visibility) => void
  /** Free-tier users see Pro-only menu items locked (badge + lock, disabled). */
  isFreeTier?: boolean
  /** Called after this clip is deleted so the list can drop the card. */
  onDeleted?: (id: string) => void
}

/** Map the clip-menu vocabulary to a registry action id (only remix-edit differs). */
function toSongAction(action: ClipMenuAction): SongActionId {
  return action === "remix-edit" ? "remix" : action
}

/**
 * Remix/Edit sub-options for the primary CTA dropdown. The flat ⋯ menu below is
 * a deliberately different shape (full §9.2 list with separators) and hardcodes
 * its own open-editor Pro lock / sample Beta badge — keep those in sync with the
 * `pro`/`beta` flags here by hand until a third consumer justifies a shared renderer.
 */
const REMIX_ITEMS: {
  action: ClipMenuAction
  label: string
  pro?: boolean
  beta?: boolean
}[] = [
  { action: "open-studio", label: "Open in Studio" },
  { action: "open-editor", label: "Open in Editor", pro: true },
  { action: "cover", label: "Cover" },
  { action: "extend", label: "Extend" },
  { action: "mashup", label: "Mashup" },
  { action: "sample", label: "Sample from Song", beta: true },
]

const DOWNLOAD_ITEMS: { action: ClipMenuAction; label: string }[] = [
  { action: "download-mp3", label: "MP3" },
  { action: "download-wav", label: "WAV" },
  { action: "download-flac", label: "FLAC" },
  { action: "download-stems", label: "Stems" },
]

/** Full clip card: metadata, playback, inline rename, and action menus. */
export function ClipCard({
  clip,
  onTitleChange,
  onMenuAction,
  onGetFullSong,
  onDislike,
  onShare,
  onVisibilityChange,
  isFreeTier = false,
  onDeleted,
}: ClipCardProps) {
  const { state, dispatch } = usePlayer()
  // Registry-driven dispatch: modal / navigation / download / delete-confirm /
  // publish (persist + guard).
  const actions = useSongActions(clip, { onDeleted })
  // likedIds re-renders every player tick; scan a Set (cf. applyClientFilters).
  const likedSet = useMemo(() => new Set(state.likedIds), [state.likedIds])
  const dislikedSet = useMemo(
    () => new Set(state.dislikedIds),
    [state.dislikedIds]
  )
  const liked = likedSet.has(clip.id)
  const disliked = dislikedSet.has(clip.id)

  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const [shareOpen, setShareOpen] = useState(false)
  // Editing cancelled (Escape) — checked in the single onBlur commit path.
  const cancelRef = useRef(false)
  // Optimistic title overlay: null means "show the prop". Keeps an idle card in
  // sync with parent/refetch updates while still reflecting the user's own edit.
  const [optimisticTitle, setOptimisticTitle] = useState<string | null>(null)
  const title = optimisticTitle ?? clip.title
  // Visibility is owned by useSongActions (optimistic + persisted + rollback).
  const visibility = actions.visibility

  const version = versionLabel(clip.model)
  const metadataLabel = modeLabel(clip.generation_mode)
  const styleText = clip.style_tags.join(", ")
  const showFullSong = isFullSongEligible(clip)

  function startEdit() {
    setDraft(title ?? "")
    setEditing(true)
  }

  // Single commit path: Enter/Escape both blur the input, so onBlur is the only
  // place a rename is saved (cancelRef distinguishes Escape). Avoids the
  // double-save / stale-closure race of committing from both keydown and blur.
  function commitEdit() {
    setEditing(false)
    if (cancelRef.current) {
      cancelRef.current = false
      return
    }
    const next = draft.trim()
    if (next && next !== (title ?? "")) {
      onTitleChange?.(clip.id, next)
      // Reflect the rename locally only when a parent can persist it — otherwise
      // the edit has nowhere to go and shouldn't look saved.
      if (onTitleChange) setOptimisticTitle(next)
    }
  }

  function emitMenu(action: ClipMenuAction) {
    // Dispatch to the shared workflow seam, then notify any observer.
    actions.handleAction(toSongAction(action))
    onMenuAction?.(action, clip.id)
  }

  function dislike() {
    dispatch({ type: "dislike/toggle", id: clip.id })
    onDislike?.(clip.id)
  }

  function share() {
    setShareOpen(true)
    onShare?.(clip.id)
  }

  function changeVisibility(next: Visibility) {
    onVisibilityChange?.(clip.id, next) // optional observer
    // Persist + guard (needs a title + style tag to go public); optimistic with
    // rollback lives in useSongActions.
    actions.setVisibility(next)
  }

  return (
    <div
      data-testid="clip-card"
      draggable
      onDragStart={(e) => {
        setClipDragData(e.dataTransfer, {
          kind: "add",
          clipId: clip.id,
          title: title ?? null,
          duration: clip.duration,
          generationMode: clip.generation_mode,
          bpm: clip.bpm,
        })
        // Track type entry, readable during dragover so studio lanes can show
        // valid/invalid drop feedback (US-19.2).
        setDragTrackType(e.dataTransfer, inferTrackType(clip.generation_mode))
      }}
      className="flex gap-3 rounded-lg border border-border bg-card p-2"
    >
      {/* Thumbnail with duration overlay + hover play. */}
      <button
        type="button"
        aria-label="Play"
        onClick={() =>
          dispatch({
            type: "play/track",
            // Use the resolved (optimistic) title so the now-playing bar matches
            // what the card shows after an inline rename.
            track: { ...trackFromClip(clip), title: title ?? "Untitled clip" },
          })
        }
        className="group/thumb relative flex size-14 shrink-0 items-center justify-center overflow-hidden rounded-md bg-muted text-muted-foreground transition-colors outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <HugeiconsIcon
          icon={MusicNote01Icon}
          size={20}
          className="group-hover/thumb:opacity-0"
        />
        <span className="absolute inset-0 flex items-center justify-center bg-background/40 opacity-0 transition-opacity group-hover/thumb:opacity-100">
          <HugeiconsIcon icon={PlayIcon} size={20} className="fill-current" />
        </span>
        {clip.duration != null && (
          <span className="absolute right-0.5 bottom-0.5 rounded bg-background/80 px-1 text-[10px] tabular-nums">
            {formatTime(clip.duration)}
          </span>
        )}
      </button>

      <div className="flex min-w-0 flex-1 flex-col justify-center gap-1">
        {/* Title (inline editable). */}
        {editing ? (
          <Input
            aria-label="Title"
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onFocus={(e) => e.currentTarget.select()}
            onBlur={commitEdit}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur()
              else if (e.key === "Escape") {
                cancelRef.current = true
                e.currentTarget.blur()
              }
            }}
            className="h-7"
          />
        ) : (
          <button
            type="button"
            aria-label="Edit title"
            onClick={startEdit}
            className="flex min-w-0 items-center gap-1 text-left outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
          >
            <span className="truncate text-sm font-medium">
              {title ?? "Untitled clip"}
            </span>
            <HugeiconsIcon
              icon={Edit02Icon}
              size={14}
              className="shrink-0 text-muted-foreground"
            />
          </button>
        )}

        {/* Badges. */}
        <div className="flex flex-wrap items-center gap-1">
          {version && (
            <Badge variant="secondary" className="text-[10px]">
              {version}
            </Badge>
          )}
          {metadataLabel && (
            <Badge variant="outline" className="text-[10px]">
              {metadataLabel}
            </Badge>
          )}
          <VisibilityBadge visibility={visibility} />
        </div>

        {/* Style description (full text on hover via title attr). */}
        {styleText && (
          <p
            title={styleText}
            className="truncate text-xs text-muted-foreground"
          >
            {styleText}
          </p>
        )}

        {/* Action row. */}
        <div className="flex flex-wrap items-center gap-0.5">
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
              size={16}
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
            <HugeiconsIcon icon={ThumbsDownIcon} size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Share"
            onClick={share}
          >
            <HugeiconsIcon icon={Share01Icon} size={16} />
          </Button>
          <VisibilityToggle value={visibility} onChange={changeVisibility} />

          {showFullSong && (
            <Button
              variant="outline"
              size="sm"
              className="ml-1"
              onClick={() => onGetFullSong?.(clip.id)}
            >
              Get Full Song
            </Button>
          )}

          <div className="ml-auto flex items-center gap-1">
            {/* Remix/Edit primary CTA. */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button size="sm" aria-label="Remix or edit clip">
                  Remix
                  <HugeiconsIcon icon={ArrowDown01Icon} size={14} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {REMIX_ITEMS.map((item) => {
                  const locked = !!item.pro && isFreeTier
                  return (
                    <DropdownMenuItem
                      key={item.action}
                      disabled={locked}
                      onSelect={() => emitMenu(item.action)}
                    >
                      {item.label}
                      {item.pro && (
                        <Badge
                          variant="outline"
                          className="ml-auto text-[10px]"
                        >
                          {locked && (
                            <HugeiconsIcon
                              icon={LockIcon}
                              data-icon="inline-start"
                            />
                          )}
                          Pro
                        </Badge>
                      )}
                      {item.beta && (
                        <Badge
                          variant="secondary"
                          className="ml-auto text-[10px]"
                        >
                          Beta
                        </Badge>
                      )}
                    </DropdownMenuItem>
                  )
                })}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* More options (⋯) — full spec §9.2 list. */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label="More options"
                >
                  <HugeiconsIcon icon={MoreHorizontalIcon} size={16} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                {/* Remix/Edit opens the remix flow; the generation actions below
                    are the flat §9.2 items (the primary CTA is the shortcut). */}
                <DropdownMenuItem onSelect={() => emitMenu("remix-edit")}>
                  Remix / Edit
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => emitMenu("open-studio")}>
                  Open in Studio
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={isFreeTier}
                  onSelect={() => emitMenu("open-editor")}
                >
                  Open in Editor
                  <Badge variant="outline" className="ml-auto text-[10px]">
                    {isFreeTier && (
                      <HugeiconsIcon icon={LockIcon} data-icon="inline-start" />
                    )}
                    Pro
                  </Badge>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => emitMenu("cover")}>
                  Cover
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => emitMenu("extend")}>
                  Extend
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => emitMenu("mashup")}>
                  Mashup
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => emitMenu("sample")}>
                  Sample from Song
                  <Badge variant="secondary" className="ml-auto text-[10px]">
                    Beta
                  </Badge>
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => emitMenu("use-inspiration")}>
                  Use as Inspiration
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => emitMenu("send-mastering")}>
                  Send to Mastering
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => emitMenu("export-daw")}>
                  Export to DAW
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => emitMenu("create-video")}>
                  Create Music Video
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>Download</DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    {DOWNLOAD_ITEMS.map((item) => (
                      <DropdownMenuItem
                        key={item.action}
                        onSelect={() => emitMenu(item.action)}
                      >
                        {item.label}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  variant="destructive"
                  onSelect={() => emitMenu("delete")}
                >
                  <HugeiconsIcon icon={Delete02Icon} size={16} />
                  Delete
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>

        {/* Download failures surface here; delete errors show in their dialog. */}
        {actions.actionError && !actions.confirmingDelete && (
          <p role="alert" className="text-xs text-destructive">
            {actions.actionError}
          </p>
        )}
      </div>

      {/* Modal-workflow actions (extend/cover/…) and delete confirmation. */}
      <SongActionModal
        clip={clip}
        action={actions.activeModal}
        onClose={actions.closeModal}
      />
      <DeleteSongDialog
        open={actions.confirmingDelete}
        title={title}
        deleting={actions.deleting}
        error={actions.actionError}
        onCancel={actions.cancelDelete}
        onConfirm={actions.confirmDelete}
      />
      <ShareModal
        open={shareOpen}
        clipId={clip.id}
        clipTitle={title}
        onClose={() => setShareOpen(false)}
      />
      <PublishGuardPrompt
        guard={actions.publishGuard}
        onClose={actions.dismissPublishGuard}
      />
    </div>
  )
}
