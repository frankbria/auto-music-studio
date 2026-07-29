"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { VideoDelivery } from "@/components/video/VideoDelivery"
import type { VideoJobState } from "@/hooks/use-video-job"
import type { VideoState } from "@/lib/video"

// Human labels for the render vocabulary (US-22.1 status endpoint).
const STATE_LABELS: Record<VideoState, string> = {
  queued: "Queued",
  rendering: "Rendering scenes",
  encoding: "Encoding video",
  complete: "Complete",
  failed: "Failed",
}

/** Round an ETA to a compact human string ("~2 min", "~45s"). */
function formatEta(seconds: number): string {
  if (seconds >= 90) return `~${Math.round(seconds / 60)} min remaining`
  return `~${Math.round(seconds)}s remaining`
}

/**
 * Minimal post-submit progress view (US-22.2): state label, progress bar with
 * percentage, ETA, and an error state with Retry. The richer progress/delivery
 * experience (phase breakdown, completion notification, download) is US-22.3.
 */
export function VideoProgress({
  state,
  songId,
  onRetry,
  onReset,
}: {
  state: VideoJobState
  /** The source song id — the completed view links its published video back here. */
  songId: string
  onRetry: () => void
  onReset: () => void
}) {
  if (state.phase === "error") {
    return (
      <div role="alert" className="flex flex-col gap-3">
        <p className="text-sm text-destructive">{state.message}</p>
        <div className="flex gap-2">
          <Button size="sm" onClick={onRetry}>
            Retry
          </Button>
          <Button size="sm" variant="outline" onClick={onReset}>
            Back to settings
          </Button>
        </div>
      </div>
    )
  }

  if (state.phase === "complete") {
    // A completed job always carries its video_id (US-22.1 status endpoint); the
    // guard keeps the type honest and degrades gracefully if it's ever absent.
    if (state.detail.video_id) {
      return (
        <VideoDelivery
          videoId={state.detail.video_id}
          songId={songId}
          onReset={onReset}
        />
      )
    }
    return (
      <div role="status" className="flex flex-col gap-3">
        <p className="text-sm font-medium">Your music video is ready.</p>
        <div>
          <Button size="sm" variant="outline" onClick={onReset}>
            Generate another
          </Button>
        </div>
      </div>
    )
  }

  // submitting / polling.
  const detail = state.phase === "polling" ? state.detail : undefined
  const status: VideoState = detail?.status ?? "queued"
  const progress = detail?.progress ?? 0

  return (
    <div role="status" className="flex flex-col gap-3">
      <span className="flex items-center gap-2 text-sm text-muted-foreground">
        <HugeiconsIcon
          icon={Loading03Icon}
          className="animate-spin"
          data-icon="inline-start"
        />
        {state.phase === "submitting" ? "Submitting…" : STATE_LABELS[status]}
      </span>
      <div
        role="progressbar"
        aria-valuenow={progress}
        aria-valuemin={0}
        aria-valuemax={100}
        className="h-2 w-full max-w-md overflow-hidden rounded-full bg-muted"
      >
        <div
          className="h-full rounded-full bg-primary transition-all"
          style={{ width: `${progress}%` }}
        />
      </div>
      <span className="text-xs text-muted-foreground tabular-nums">
        {progress}%
        {detail?.eta_seconds != null && ` · ${formatEta(detail.eta_seconds)}`}
      </span>
    </div>
  )
}
