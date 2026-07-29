"use client"

import { useState } from "react"
import Link from "next/link"

import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import { publishVideo, videoStreamUrl } from "@/lib/video"

type PublishState =
  | { status: "idle" }
  | { status: "publishing" }
  | { status: "published" }
  | { status: "error"; message: string }

/**
 * The completed-render delivery view (US-22.3): an in-browser player, an MP4
 * download, and a Publish button that surfaces the video on the song page.
 *
 * The player and download link point at the BFF stream proxy, which falls back
 * to the httpOnly access cookie so these credential-less elements can fetch a
 * still-private (unpublished) render. Publish uses the Bearer token (owner-only).
 */
export function VideoDelivery({
  videoId,
  songId,
  onReset,
}: {
  videoId: string
  songId: string
  onReset: () => void
}) {
  const { accessToken } = useAuth()
  const [publish, setPublish] = useState<PublishState>({ status: "idle" })

  async function handlePublish() {
    setPublish({ status: "publishing" })
    const result = await publishVideo(videoId, accessToken ?? "")
    switch (result.status) {
      case "published":
        setPublish({ status: "published" })
        return
      case "unauthorized":
        setPublish({ status: "error", message: "Please sign in again to publish." })
        return
      case "not_found":
        setPublish({ status: "error", message: "This video is no longer available." })
        return
      case "error":
        setPublish({ status: "error", message: result.detail })
        return
    }
  }

  return (
    <div role="status" className="flex flex-col gap-3">
      <p className="text-sm font-medium">Your music video is ready.</p>
      <video
        controls
        src={videoStreamUrl(videoId)}
        className="w-full max-w-2xl rounded-lg border bg-black"
        data-testid="video-delivery-player"
      />
      <div className="flex flex-wrap gap-2">
        <Button asChild size="sm">
          {/* Content-Disposition on the proxied response drives the save-to-disk. */}
          <a href={videoStreamUrl(videoId, { download: true })} download>
            Download MP4
          </a>
        </Button>
        {publish.status === "published" ? (
          <Button asChild size="sm" variant="outline">
            <Link href={`/song/${songId}`}>View on song page</Link>
          </Button>
        ) : (
          <Button
            size="sm"
            variant="outline"
            onClick={handlePublish}
            disabled={publish.status === "publishing"}
          >
            {publish.status === "publishing" ? "Publishing…" : "Publish to song page"}
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onReset}>
          Generate another
        </Button>
      </div>
      {publish.status === "published" && (
        <p className="text-sm text-muted-foreground">
          Published — it now appears on the song page.
        </p>
      )}
      {publish.status === "error" && (
        <p role="alert" className="text-sm text-destructive">
          {publish.message}
        </p>
      )}
    </div>
  )
}
