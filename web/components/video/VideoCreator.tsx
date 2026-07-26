"use client"

import Link from "next/link"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { SourceSongCard } from "@/components/video/SourceSongCard"
import { VideoForm } from "@/components/video/VideoForm"
import { VideoProgress } from "@/components/video/VideoProgress"
import { useClip } from "@/hooks/use-clip"
import { useRequireAuth } from "@/hooks/use-require-auth"
import { useVideoJob } from "@/hooks/use-video-job"
import type { VideoConfig } from "@/lib/video"

/**
 * Video creation page content (US-22.2): the source song, the render
 * configuration form, and — once submitted — the progress view. The form and
 * progress swap in place; submitting is a one-way transition until the job
 * completes, fails, or is reset.
 */
export function VideoCreator({ songId }: { songId: string }) {
  const { isLoading: authLoading, isAuthenticated } = useRequireAuth()
  const { clip, loading, notFound } = useClip(songId)
  const { state, submit, retry, reset } = useVideoJob()

  // Render nothing until authed — useRequireAuth redirects otherwise (mirrors
  // app/release/page.tsx).
  if (authLoading || !isAuthenticated) return null

  function handleGenerate(config: VideoConfig) {
    void submit(songId, config)
  }

  return (
    <div className="flex flex-col gap-6 p-8">
      <h1 className="text-2xl font-semibold">Create Music Video</h1>

      {loading ? (
        <p role="status" className="text-sm text-muted-foreground">
          Loading song…
        </p>
      ) : notFound || !clip ? (
        <Card>
          <CardHeader>
            <CardTitle>Song not found</CardTitle>
            <CardDescription>
              That song is unavailable.{" "}
              <Link
                href="/dashboard"
                className="underline underline-offset-2 hover:text-foreground"
              >
                Back to your songs
              </Link>
              .
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <SourceSongCard clip={clip} />
          <Card>
            <CardHeader>
              <CardTitle>Visual settings</CardTitle>
              <CardDescription>
                Describe the look of your video, or start from a preset.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {state.phase === "idle" ? (
                <VideoForm clip={clip} onGenerate={handleGenerate} />
              ) : (
                <VideoProgress state={state} onRetry={retry} onReset={reset} />
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  )
}
