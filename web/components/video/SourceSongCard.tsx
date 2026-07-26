"use client"

import { useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon, PauseIcon, PlayIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { clipAudioUrl, formatTime } from "@/lib/clips"
import type { Clip } from "@/lib/workspace-clips"

/**
 * Source-song card for the video page (US-22.2): music-glyph thumbnail (no
 * artwork proxy exists in web/), title, duration, style tags, and play/pause
 * driven by the cookie-authed `/stream` proxy (preview-player idiom).
 */
export function SourceSongCard({ clip }: { clip: Clip }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const [playing, setPlaying] = useState(false)

  function togglePlay() {
    const audio = audioRef.current
    if (!audio) return
    // jsdom's play() is a no-op stub; optional-chain the promise so a rejected
    // autoplay (or the stub) never throws.
    if (audio.paused) audio.play()?.catch(() => {})
    else audio.pause()
  }

  return (
    <Card>
      <CardContent className="flex items-center gap-4 p-4">
        <audio
          ref={audioRef}
          src={clipAudioUrl(clip.id)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          data-testid="source-audio"
        />

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
          {clip.style_tags.length > 0 && (
            <div className="flex flex-wrap items-center gap-1 pt-1">
              {clip.style_tags.map((tag) => (
                <Badge key={tag} variant="secondary">
                  {tag}
                </Badge>
              ))}
            </div>
          )}
        </div>

        <Button
          type="button"
          size="icon"
          variant="secondary"
          onClick={togglePlay}
          aria-label={playing ? "Pause" : "Play"}
        >
          <HugeiconsIcon icon={playing ? PauseIcon : PlayIcon} size={18} />
        </Button>
      </CardContent>
    </Card>
  )
}
