"use client"

import { useEffect, useRef, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import {
  fetchPublishedVideoForClip,
  videoStreamUrl,
  type VideoDetail,
} from "@/lib/video"

/**
 * The song page's "Music video" section (US-22.3 AC5): renders the clip's
 * published video, or nothing when there isn't one. The page is public, so this
 * works for a signed-out visitor on a public clip; the owner's token (when
 * present) also surfaces a video published on a still-private clip.
 */
export function SongVideo({ clipId }: { clipId: string }) {
  const { accessToken } = useAuth()
  const [video, setVideo] = useState<VideoDetail | null>(null)
  const mounted = useRef(true)

  useEffect(() => {
    mounted.current = true
    void fetchPublishedVideoForClip(clipId, accessToken ?? undefined).then((v) => {
      if (mounted.current) setVideo(v)
    })
    return () => {
      mounted.current = false
    }
  }, [clipId, accessToken])

  if (!video) return null

  return (
    <section aria-label="Music video" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold">Music video</h2>
      <video
        controls
        src={videoStreamUrl(video.id)}
        className="w-full max-w-2xl rounded-lg border bg-black"
        data-testid="song-video-player"
      />
    </section>
  )
}
