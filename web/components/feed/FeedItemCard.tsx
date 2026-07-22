"use client"

import { useEffect, useRef, useState } from "react"
import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  FavouriteIcon,
  MusicNote01Icon,
  PauseIcon,
  PlayIcon,
  RepeatIcon,
  Share01Icon,
  SparklesIcon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { ShareModal } from "@/components/song/ShareModal"
import { usePlayer } from "@/contexts/player-context"
import { clipInspirationHref, type FeedItem } from "@/lib/feed"
import { cn } from "@/lib/utils"

// One short-form feed item (US-20.4). Full-height card with a glyph artwork
// backdrop (no authed artwork proxy), title/artist/tag overlays, and an action
// rail. Owns its own <audio>: an effect drives play/pause off the `active` prop
// (the in-view item), which is a side-effect syncing to an external element — not
// set-state-in-effect. The play/pause icon tracks the element's own events.

/** Vertical action-rail button. */
function RailButton({
  icon,
  label,
  active,
  onClick,
  href,
}: {
  icon: typeof PlayIcon
  label: string
  active?: boolean
  onClick?: () => void
  href?: string
}) {
  const className = cn(
    "flex flex-col items-center gap-1 rounded-lg p-2 text-white/90 outline-none transition-colors hover:bg-white/10 focus-visible:ring-3 focus-visible:ring-white/40",
    active && "text-primary"
  )
  const inner = (
    <>
      <HugeiconsIcon
        icon={icon}
        size={26}
        className={cn(active && "fill-current")}
      />
      <span className="text-[11px] font-medium">{label}</span>
    </>
  )
  return href ? (
    <Link href={href} aria-label={label} className={className}>
      {inner}
    </Link>
  ) : (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      onClick={onClick}
      className={className}
    >
      {inner}
    </button>
  )
}

export function FeedItemCard({
  item,
  active,
}: {
  item: FeedItem
  /** True when this is the in-view item — drives auto-play. */
  active: boolean
}) {
  const { state, dispatch } = usePlayer()
  const audioRef = useRef<HTMLAudioElement>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)

  const liked = state.likedIds.includes(item.id)
  const styleText = item.style_tags.join(", ")

  // Sync the audio element to `active`: play when scrolled into view, pause when
  // out. play() may reject under the browser autoplay policy (no gesture yet); we
  // swallow it and the play button stays available. No setState here.
  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    if (active) {
      void audio.play().catch(() => {})
    } else {
      audio.pause()
      audio.currentTime = 0
    }
  }, [active])

  const togglePlay = () => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) void audio.play().catch(() => {})
    else audio.pause()
  }

  return (
    <section
      data-testid="feed-item"
      data-active={active}
      aria-label={`${item.title ?? "Untitled clip"} by ${item.artist}`}
      className="relative flex h-full w-full items-stretch justify-center p-3"
    >
      {/* Artwork backdrop: glyph + gradient for text legibility. */}
      <button
        type="button"
        onClick={togglePlay}
        aria-label={isPlaying ? "Pause" : "Play"}
        className="group relative w-full max-w-md overflow-hidden rounded-2xl bg-gradient-to-b from-muted to-muted-foreground/20 outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
      >
        <span className="absolute inset-0 flex items-center justify-center text-muted-foreground/40">
          <HugeiconsIcon icon={MusicNote01Icon} size={96} aria-hidden />
        </span>
        {/* Center play/pause affordance; visible when paused or on hover. */}
        <span
          className={cn(
            "absolute inset-0 flex items-center justify-center bg-black/10 transition-opacity",
            isPlaying ? "opacity-0 group-hover:opacity-100" : "opacity-100"
          )}
        >
          <span className="flex size-16 items-center justify-center rounded-full bg-black/45 text-white">
            <HugeiconsIcon icon={isPlaying ? PauseIcon : PlayIcon} size={32} />
          </span>
        </span>
        {/* Bottom gradient scrim behind the text overlays. */}
        <span className="absolute inset-x-0 bottom-0 h-2/5 bg-gradient-to-t from-black/70 to-transparent" />
      </button>

      {/* Text overlays (title / artist / tags). */}
      <div className="pointer-events-none absolute inset-x-0 bottom-0 mx-auto flex max-w-md flex-col gap-2 p-5 pr-16 text-white">
        <h2 className="text-lg font-semibold drop-shadow">
          {item.title ?? "Untitled clip"}
        </h2>
        <p className="text-sm text-white/80 drop-shadow">{item.artist}</p>
        {styleText && (
          <div className="flex flex-wrap gap-1">
            {item.style_tags.map((tag) => (
              <Badge key={tag} variant="secondary" className="bg-white/15 text-white">
                {tag}
              </Badge>
            ))}
          </div>
        )}
      </div>

      {/* Action rail. */}
      <div className="absolute right-2 bottom-6 flex flex-col items-center gap-3">
        <RailButton
          icon={FavouriteIcon}
          label={liked ? "Liked" : "Like"}
          active={liked}
          onClick={() => dispatch({ type: "like/toggle", id: item.id })}
        />
        <RailButton
          icon={Share01Icon}
          label="Share"
          onClick={() => setShareOpen(true)}
        />
        <RailButton icon={RepeatIcon} label="Remix" href={`/song/${item.id}`} />
        <RailButton
          icon={SparklesIcon}
          label="Inspire"
          href={clipInspirationHref(item)}
        />
      </div>

      <audio
        ref={audioRef}
        src={item.audioUrl}
        loop
        preload="none"
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        data-testid="feed-audio"
      />

      <ShareModal
        open={shareOpen}
        clipId={item.id}
        clipTitle={item.title}
        onClose={() => setShareOpen(false)}
      />
    </section>
  )
}
