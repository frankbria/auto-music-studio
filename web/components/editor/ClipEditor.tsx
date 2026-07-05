"use client"

import { WaveformEditor } from "@/components/editor/WaveformEditor"
import { useAuth } from "@/hooks/use-auth"
import { useClip } from "@/hooks/use-clip"
import { useClipAudio } from "@/hooks/use-clip-audio"
import { useRequireAuth } from "@/hooks/use-require-auth"
import type { Clip } from "@/lib/workspace-clips"

// Waveform-editor view (US-18.1). Mirrors SongDetail's shape: holds all the
// auth / data / audio-decode logic so the App Router page stays a thin
// params→component shim. Takes a plain clipId, so it's easy to test.

export function ClipEditor({ clipId }: { clipId: string }) {
  const { isLoading: authLoading, isAuthenticated } = useRequireAuth()
  const { clip, loading, error, notFound } = useClip(clipId)

  if (authLoading || !isAuthenticated) return null

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl space-y-3 p-8" data-testid="editor-loading">
        <div className="h-8 w-64 animate-pulse rounded bg-muted" />
        <div className="h-48 animate-pulse rounded-lg bg-muted" />
      </div>
    )
  }

  if (notFound) {
    return (
      <div className="mx-auto max-w-6xl p-8" data-testid="editor-not-found">
        <h1 className="text-xl font-semibold">Clip not found</h1>
        <p className="text-sm text-muted-foreground">
          This clip doesn&apos;t exist or you don&apos;t have access to it.
        </p>
      </div>
    )
  }

  if (error || !clip) {
    return (
      <div className="mx-auto max-w-6xl p-8" data-testid="editor-error">
        <h1 className="text-xl font-semibold">Couldn&apos;t load this clip</h1>
        <p className="text-sm text-muted-foreground">
          Something went wrong. Please try again.
        </p>
      </div>
    )
  }

  // key by clip id so the viewport/audio reset cleanly between clips.
  return <ClipEditorContent key={clip.id} clip={clip} />
}

function ClipEditorContent({ clip }: { clip: Clip }) {
  const { accessToken } = useAuth()
  const audioState = useClipAudio(clip.id, accessToken)

  return (
    <div className="mx-auto max-w-6xl p-8">
      {audioState.status === "loading" && (
        <div className="space-y-3" data-testid="editor-audio-loading">
          <div className="h-8 w-64 animate-pulse rounded bg-muted" />
          <div className="h-48 animate-pulse rounded-lg bg-muted" />
          <p className="text-sm text-muted-foreground">Decoding audio…</p>
        </div>
      )}

      {audioState.status === "error" && (
        <div data-testid="editor-audio-error">
          <h1 className="text-xl font-semibold">Couldn&apos;t load the audio</h1>
          <p className="text-sm text-muted-foreground">
            The clip&apos;s audio couldn&apos;t be decoded. Please try again.
          </p>
        </div>
      )}

      {audioState.status === "ready" && (
        <WaveformEditor clip={clip} audio={audioState.audio} />
      )}
    </div>
  )
}
