"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  ArrowDown01Icon,
  Delete02Icon,
  Edit02Icon,
  FavouriteIcon,
  GlobeIcon,
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
import { usePlayer } from "@/contexts/player-context"
import { clipArtworkUrl, clipAudioUrl, formatTime, type Track } from "@/lib/clips"
import { cn } from "@/lib/utils"
import type { Clip } from "@/lib/workspace-clips"

// US-16.6: the reusable clip card. Play + Like are wired to the global player
// store (the only backend-free actions that already have a home — see
// LikeButton). Everything else is exposed as a callback prop because the backend
// has no like/dislike/share/publish/title/menu endpoints proxied in web/ yet;
// the parent (or a future hook) wires those when the routes land.

/** Every action reachable from the clip card menus (spec §9.2). */
export type ClipMenuAction =
  | "remix-edit"
  | "open-studio"
  | "open-editor"
  | "cover"
  | "extend"
  | "mashup"
  | "sample"
  | "use-inspiration"
  | "send-mastering"
  | "export-daw"
  | "create-video"
  | "download-mp3"
  | "download-wav"
  | "download-flac"
  | "download-stems"
  | "delete"

export type ClipCardProps = {
  clip: Clip
  /** Inline-rename committed (blur/Enter). */
  onTitleChange?: (id: string, title: string) => void
  /** Any menu item from the Remix/Edit CTA or the ⋯ menu. */
  onMenuAction?: (action: ClipMenuAction, clipId: string) => void
  onGetFullSong?: (id: string) => void
  onDislike?: (id: string) => void
  onShare?: (id: string) => void
  /** Publish toggle; `next` is the requested visibility. */
  onPublishToggle?: (id: string, next: boolean) => void
}

const FULL_SONG_MAX_SECONDS = 60

/** Model id → short version badge label. Unmapped models show their raw id. */
const VERSION_LABELS: Record<string, string> = {
  "ace-step-v1": "XL",
  "ace-step-v1-turbo": "XL Turbo",
}

/** generation_mode → metadata badge label. Plain "generate"/null show nothing. */
const MODE_LABELS: Record<string, string> = {
  cover: "Cover",
  extend: "Extend",
  remix: "Remix",
  mashup: "Mashup",
  sample: "Sample",
  upload: "Upload",
  studio: "Studio",
  mastered: "Mastered",
  full_song: "Full Song",
}

/** Remix/Edit sub-options, shared by the primary CTA and the ⋯ submenu. */
const REMIX_ITEMS: { action: ClipMenuAction; label: string; pro?: boolean }[] = [
  { action: "open-studio", label: "Open in Studio" },
  { action: "open-editor", label: "Open in Editor", pro: true },
  { action: "cover", label: "Cover" },
  { action: "extend", label: "Extend" },
  { action: "mashup", label: "Mashup" },
  { action: "sample", label: "Sample from Song" },
]

const DOWNLOAD_ITEMS: { action: ClipMenuAction; label: string }[] = [
  { action: "download-mp3", label: "MP3" },
  { action: "download-wav", label: "WAV" },
  { action: "download-flac", label: "FLAC" },
  { action: "download-stems", label: "Stems" },
]

/** Build a playable Track from a clip (artist/artwork are placeholders today). */
function trackFromClip(clip: Clip): Track {
  return {
    id: clip.id,
    title: clip.title ?? "Untitled clip",
    artist: "Unknown artist",
    audioUrl: clipAudioUrl(clip.id),
    artworkUrl: clipArtworkUrl(clip.id),
    duration: clip.duration ?? undefined,
  }
}

/** Full clip card: metadata, playback, inline rename, and action menus. */
export function ClipCard({
  clip,
  onTitleChange,
  onMenuAction,
  onGetFullSong,
  onDislike,
  onShare,
  onPublishToggle,
}: ClipCardProps) {
  const { state, dispatch } = usePlayer()
  const liked = state.likedIds.includes(clip.id)

  const [title, setTitle] = useState(clip.title)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState("")
  const [isPublic, setIsPublic] = useState(clip.is_public)

  const versionLabel = clip.model
    ? (VERSION_LABELS[clip.model] ?? clip.model)
    : null
  const metadataLabel = clip.generation_mode
    ? MODE_LABELS[clip.generation_mode]
    : null
  const styleText = clip.style_tags.join(", ")
  const showFullSong =
    clip.duration != null && clip.duration < FULL_SONG_MAX_SECONDS

  function startEdit() {
    setDraft(title ?? "")
    setEditing(true)
  }

  function commitEdit() {
    if (!editing) return
    setEditing(false)
    const next = draft.trim()
    if (next && next !== (title ?? "")) {
      setTitle(next)
      onTitleChange?.(clip.id, next)
    }
  }

  function emitMenu(action: ClipMenuAction) {
    onMenuAction?.(action, clip.id)
  }

  function togglePublish() {
    const next = !isPublic
    setIsPublic(next)
    onPublishToggle?.(clip.id, next)
  }

  return (
    <div
      data-testid="clip-card"
      className="flex gap-3 rounded-lg border border-border bg-card p-2"
    >
      {/* Thumbnail with duration overlay + hover play. */}
      <button
        type="button"
        aria-label="Play"
        onClick={() => dispatch({ type: "play/track", track: trackFromClip(clip) })}
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
              if (e.key === "Enter") commitEdit()
              else if (e.key === "Escape") setEditing(false)
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
        {(versionLabel || metadataLabel) && (
          <div className="flex flex-wrap items-center gap-1">
            {versionLabel && (
              <Badge variant="secondary" className="text-[10px]">
                {versionLabel}
              </Badge>
            )}
            {metadataLabel && (
              <Badge variant="outline" className="text-[10px]">
                {metadataLabel}
              </Badge>
            )}
          </div>
        )}

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
            onClick={() => onDislike?.(clip.id)}
          >
            <HugeiconsIcon icon={ThumbsDownIcon} size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Share"
            onClick={() => onShare?.(clip.id)}
          >
            <HugeiconsIcon icon={Share01Icon} size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label={isPublic ? "Unpublish (make private)" : "Publish (make public)"}
            aria-pressed={isPublic}
            onClick={togglePublish}
            className={cn(isPublic && "text-primary")}
          >
            <HugeiconsIcon icon={GlobeIcon} size={16} />
          </Button>

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
                {REMIX_ITEMS.map((item) => (
                  <DropdownMenuItem
                    key={item.action}
                    onSelect={() => emitMenu(item.action)}
                  >
                    {item.label}
                    {item.pro && (
                      <Badge variant="outline" className="ml-auto text-[10px]">
                        Pro
                      </Badge>
                    )}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>

            {/* More options (⋯) — full spec §9.2 list. */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon-sm" aria-label="More options">
                  <HugeiconsIcon icon={MoreHorizontalIcon} size={16} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-52">
                <DropdownMenuSub>
                  <DropdownMenuSubTrigger>Remix / Edit</DropdownMenuSubTrigger>
                  <DropdownMenuSubContent>
                    {REMIX_ITEMS.map((item) => (
                      <DropdownMenuItem
                        key={item.action}
                        onSelect={() => emitMenu(item.action)}
                      >
                        {item.label}
                        {item.pro && (
                          <Badge
                            variant="outline"
                            className="ml-auto text-[10px]"
                          >
                            Pro
                          </Badge>
                        )}
                      </DropdownMenuItem>
                    ))}
                  </DropdownMenuSubContent>
                </DropdownMenuSub>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => emitMenu("open-studio")}>
                  Open in Studio
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => emitMenu("open-editor")}>
                  Open in Editor
                  <Badge variant="outline" className="ml-auto text-[10px]">
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
      </div>
    </div>
  )
}
