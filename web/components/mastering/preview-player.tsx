"use client"

import { useRef, useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { PauseIcon, PlayIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { clipAudioUrl, formatTime } from "@/lib/clips"

type ABMode = "original" | "mastered"

/**
 * A/B preview player (US-21.2). One `<audio>` element whose source swaps between
 * the original mix and the selected master, so the two are auditioned at the
 * same playback position — true A/B comparison.
 *
 * Both sources are driven by clip id through the cookie-authed `/stream` proxy
 * (issue #282): the mastered preview id and the source clip id are both clip
 * ids, so no raw storage URL is needed. On a toggle the current time + play
 * state are captured and restored once the new source loads (seamless switch).
 */
export function PreviewPlayer({
  originalClipId,
  masteredClipId,
}: {
  originalClipId: string
  masteredClipId: string
}) {
  const audioRef = useRef<HTMLAudioElement>(null)
  // Position + play state to restore after a source swap (seamless A/B).
  const pendingRef = useRef<{ time: number; play: boolean } | null>(null)

  const [mode, setMode] = useState<ABMode>("mastered")
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)

  const src = clipAudioUrl(mode === "mastered" ? masteredClipId : originalClipId)

  function safePlay() {
    // jsdom's play() is a no-op stub; optional-chain the promise so a rejected
    // autoplay (or the stub) never throws.
    audioRef.current?.play()?.catch(() => {})
  }

  function togglePlay() {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) safePlay()
    else audio.pause()
  }

  function toggleMode() {
    const audio = audioRef.current
    if (audio) {
      pendingRef.current = { time: audio.currentTime, play: !audio.paused }
    }
    setMode((m) => (m === "mastered" ? "original" : "mastered"))
  }

  // Restore position + resume once the swapped-in source is seekable.
  function handleLoadedMetadata() {
    const audio = audioRef.current
    if (!audio) return
    setDuration(audio.duration || 0)
    const pending = pendingRef.current
    if (pending) {
      audio.currentTime = pending.time
      if (pending.play) safePlay()
      pendingRef.current = null
    }
  }

  function handleSeek(e: React.ChangeEvent<HTMLInputElement>) {
    const audio = audioRef.current
    const t = Number(e.target.value)
    if (audio) audio.currentTime = t
    setCurrentTime(t)
  }

  return (
    <div className="flex flex-col gap-3">
      <audio
        ref={audioRef}
        src={src}
        onPlay={() => setPlaying(true)}
        onPause={() => setPlaying(false)}
        onEnded={() => setPlaying(false)}
        onLoadedMetadata={handleLoadedMetadata}
        onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
        data-testid="preview-audio"
      />

      <div className="flex items-center gap-3">
        <Button
          type="button"
          size="icon"
          variant="secondary"
          onClick={togglePlay}
          aria-label={playing ? "Pause" : "Play"}
        >
          <HugeiconsIcon icon={playing ? PauseIcon : PlayIcon} size={18} />
        </Button>

        <span className="text-xs text-muted-foreground tabular-nums">
          {formatTime(currentTime)} / {formatTime(duration)}
        </span>

        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={handleSeek}
          aria-label="Seek"
          className="flex-1 accent-primary"
        />
      </div>

      <div className="flex items-center gap-3">
        <span className="text-sm font-medium">
          Now playing:{" "}
          <span data-testid="ab-mode">
            {mode === "mastered" ? "Mastered" : "Original"}
          </span>
        </span>
        <Button type="button" variant="outline" size="sm" onClick={toggleMode}>
          Compare with {mode === "mastered" ? "Original" : "Mastered"}
        </Button>
      </div>
    </div>
  )
}
