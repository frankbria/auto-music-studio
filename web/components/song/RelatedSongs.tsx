"use client"

import { ClipCard } from "@/components/workspace/ClipCard"
import { useSimilarClips } from "@/hooks/use-similar-clips"

// Song-detail "Related songs" panel (US-17.1). Pulls similar clips from the
// /similar endpoint and renders them with the shared ClipCard. Loading shows
// skeletons; an empty/failed result hides the panel rather than showing a dead
// "no results" block — related songs are supplementary.

export function RelatedSongs({ clipId }: { clipId: string }) {
  const { clips, loading } = useSimilarClips(clipId)

  if (loading) {
    return (
      <div className="flex flex-col gap-2" data-testid="related-loading">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    )
  }

  if (clips.length === 0) return null

  return (
    <section aria-label="Related songs" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold">Related songs</h2>
      <div className="flex flex-col gap-2">
        {clips.map((clip) => (
          <ClipCard key={clip.id} clip={clip} />
        ))}
      </div>
    </section>
  )
}
