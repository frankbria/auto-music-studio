"use client"

import { ReportClipButton } from "@/components/moderation/ReportClipButton"
import { ClipCard } from "@/components/workspace/ClipCard"
import { useSimilarClips } from "@/hooks/use-similar-clips"

// Song-detail "Related songs" panel (US-17.1). Pulls similar clips from the
// /similar endpoint and renders them with the shared ClipCard. Loading shows
// skeletons; an empty/failed result hides the panel rather than showing a dead
// "no results" block — related songs are supplementary. Report (US-27.2, #535)
// shows only when the server says the clip isn't the viewer's; an absent
// is_owner hides it rather than risk a Report on your own clip.

export function RelatedSongs({
  clipId,
  isFreeTier,
}: {
  clipId: string
  /** Threaded to each card so Pro-gating matches the page's main action menu (US-17.5). */
  isFreeTier?: boolean
}) {
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
      <ul className="flex flex-col gap-2">
        {clips.map((clip) => (
          <li key={clip.id} className="flex items-start gap-1">
            <div className="min-w-0 flex-1">
              <ClipCard clip={clip} isFreeTier={isFreeTier} />
            </div>
            {/* Fixed gutter keeps cards the same width whether or not Report shows. */}
            <div className="w-8 shrink-0">
              <ReportClipButton
                clipId={clip.id}
                isOwner={clip.is_owner !== false}
              />
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
