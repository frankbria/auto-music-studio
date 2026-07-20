import type { Clip } from "@/lib/workspace-clips"
import { ExploreClipCard } from "./ExploreClipCard"
import { SectionRow } from "./SectionRow"

// Generic titled clip row for Explore (US-20.1). Staff Picks, New Releases, and
// Charts are all "title + a scroll row of clip cards"; the only difference is
// that Charts shows ranking numbers, so `ranked` adds a 1-based rank overlay.
// Keeping one component avoids three near-identical copies.

export function ClipSection({
  title,
  clips,
  ranked = false,
}: {
  title: string
  clips: Clip[]
  /** Charts: show a 1-based ranking number on each card (AC4). */
  ranked?: boolean
}) {
  if (clips.length === 0) return null
  return (
    <SectionRow title={title}>
      {clips.map((clip, i) => (
        <ExploreClipCard
          key={clip.id}
          clip={clip}
          rank={ranked ? i + 1 : undefined}
        />
      ))}
    </SectionRow>
  )
}
