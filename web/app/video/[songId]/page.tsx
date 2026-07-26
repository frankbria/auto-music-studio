"use client"

import { useParams } from "next/navigation"

import { VideoCreator } from "@/components/video/VideoCreator"

// Video creation page (US-22.2). Thin shim over VideoCreator (editor/[id]
// idiom) so the content is testable without a navigation mock.
export default function VideoPage() {
  const params = useParams<{ songId: string }>()
  const songId = params?.songId
  if (!songId) return null
  return <VideoCreator songId={songId} />
}
