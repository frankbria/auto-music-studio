"use client"

import { useParams, useSearchParams } from "next/navigation"

import { VideoAppealPanel } from "@/components/moderation/VideoAppealPanel"
import { VideoCreator } from "@/components/video/VideoCreator"

// Video creation page (US-22.2). Thin shim over VideoCreator (editor/[id]
// idiom) so the content is testable without a navigation mock.
export default function VideoPage() {
  const params = useParams<{ songId: string }>()
  const songId = params?.songId
  // The takedown notice links here with the video it took down (#623).
  const appealVideoId = useSearchParams()?.get("appeal")
  if (!songId) return null
  return (
    <>
      {appealVideoId && <VideoAppealPanel videoId={appealVideoId} />}
      <VideoCreator songId={songId} />
    </>
  )
}
