"use client"

import { useContext } from "react"

import { VideoAppealStatus } from "@/components/moderation/ClipAppealStatus"
import { AuthContext } from "@/contexts/auth-context"
import { useMyAppeals } from "@/hooks/use-my-appeals"
import { appealForVideo } from "@/lib/appeals"

// A taken-down video's moderation status and its appeal (#623): shown where the
// owner meets the takedown, from the notice's link or a refused Publish.
export function VideoAppealPanel({ videoId }: { videoId: string }) {
  const auth = useContext(AuthContext)
  const { appeals } = useMyAppeals(auth?.accessToken ?? null)
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
        appeal={appealForVideo(appeals, videoId)}
      />
    </section>
  )
}
