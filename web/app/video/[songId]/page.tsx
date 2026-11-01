"use client"

import { Suspense } from "react"
import { useParams, useSearchParams } from "next/navigation"

import { VideoAppealPanel } from "@/components/moderation/VideoAppealPanel"
import { VideoCreator } from "@/components/video/VideoCreator"

// Video creation page (US-22.2). Thin shim over VideoCreator (editor/[id]
// idiom) so the content is testable without a navigation mock.
export default function VideoPage() {
  const params = useParams<{ songId: string }>()
  const songId = params?.songId
  if (!songId) return null
  return (
    <>
      {/* Suspense: reading search params bails out of prerender; see app/create/page.tsx. */}
      <Suspense fallback={null}>
        <AppealFromNotice />
      </Suspense>
      <VideoCreator songId={songId} />
    </>
  )
}

/** The takedown notice links here with the video it took down (#623). */
function AppealFromNotice() {
  const videoId = useSearchParams()?.get("appeal")
  return videoId ? <VideoAppealPanel videoId={videoId} /> : null
}
