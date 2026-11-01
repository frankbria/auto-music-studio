"use client"

import { useContext, useEffect, useState } from "react"

import { VideoAppealStatus } from "@/components/moderation/ClipAppealStatus"
import { AuthContext } from "@/contexts/auth-context"
import { useMyAppeals } from "@/hooks/use-my-appeals"
import { appealForVideo } from "@/lib/appeals"
import { fetchVideoDetail } from "@/lib/video"

// A taken-down video's moderation status and its appeal (#623): shown where the
// owner meets the takedown, from the notice's link or a refused Publish.
export function VideoAppealPanel({ videoId }: { videoId: string }) {
  const auth = useContext(AuthContext)
  const accessToken = auth?.accessToken ?? null
  const { appeals } = useMyAppeals(accessToken)
  // When the takedown in force was made: an appeal older than it was against an earlier one.
  const [decidedAt, setDecidedAt] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    void fetchVideoDetail(videoId, accessToken ?? undefined).then((video) => {
      if (active) setDecidedAt(video?.taken_down_at ?? null)
    })
    return () => {
      active = false
    }
  }, [videoId, accessToken])

  return (
    <section
      aria-label="Video moderation"
      className="flex flex-col gap-2 rounded-lg border border-destructive/40 p-3"
    >
      <p className="text-sm">
        Moderation took this video down. It can&apos;t be published unless the
        decision is reversed.
      </p>
      <VideoAppealStatus
        videoId={videoId}
        decidedAt={decidedAt}
        appeal={appealForVideo(appeals, videoId)}
      />
    </section>
  )
}
