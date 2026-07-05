"use client"

import { LineageChain } from "@/components/song/LineageChain"
import { useLineage } from "@/hooks/use-lineage"
import { lineageColumns } from "@/lib/lineage"
import type { Clip } from "@/lib/workspace-clips"

// Song-detail "Generation history" panel (US-17.7). Shows how the current clip was
// derived from its ancestors as a horizontal chain. An original clip (no parents)
// renders nothing — and skips the fetch entirely, since the subject clip already
// tells us it has no lineage. Errors/empty degrade quietly like RelatedSongs;
// lineage is supplementary and shouldn't leave a dead block on the page.

export function LineageSection({ clip }: { clip: Clip }) {
  // Originals have no ancestry to show; short-circuit before hitting the API.
  if (clip.parent_clip_ids.length === 0) return null
  return <LineageSectionInner clipId={clip.id} />
}

function LineageSectionInner({ clipId }: { clipId: string }) {
  const { nodes, truncated, loading } = useLineage(clipId)

  if (loading) {
    return (
      <section aria-label="Generation history" className="flex flex-col gap-3">
        <h2 className="text-sm font-semibold">Generation history</h2>
        <div className="h-24 animate-pulse rounded-lg bg-muted" data-testid="lineage-loading" />
      </section>
    )
  }

  const columns = lineageColumns(nodes)
  // No ancestors resolved (all owned by others, or the fetch failed) — hide.
  if (columns.length === 0) return null

  return (
    <section aria-label="Generation history" className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold">Generation history</h2>
      <LineageChain columns={columns} truncated={truncated} />
    </section>
  )
}
