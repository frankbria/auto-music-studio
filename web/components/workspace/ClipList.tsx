"use client"

import { ClipCard } from "@/components/workspace/ClipCard"
import type { Clip } from "@/lib/workspace-clips"

/** Renders clip cards, a loading skeleton, or an empty-state message. */
export function ClipList({
  clips,
  loading,
  emptyMessage = "No clips found.",
  onGetFullSong,
  isFreeTier,
  onDeleted,
}: {
  clips: Clip[]
  loading: boolean
  emptyMessage?: string
  /** Open the Get Full Song wizard for an eligible clip (US-17.4). */
  onGetFullSong?: (id: string) => void
  /** Locks Pro-only context-menu items for free-tier users (US-17.5). */
  isFreeTier?: boolean
  /** Drop a card after its clip is deleted from the context menu (US-17.5). */
  onDeleted?: (id: string) => void
}) {
  if (loading) {
    return (
      <div className="flex flex-col gap-2" data-testid="clip-list-skeleton">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-[72px] animate-pulse rounded-lg bg-muted" />
        ))}
      </div>
    )
  }

  if (clips.length === 0) {
    return (
      <p className="py-8 text-center text-sm text-muted-foreground">
        {emptyMessage}
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-2">
      {clips.map((clip) => (
        <ClipCard
          key={clip.id}
          clip={clip}
          onGetFullSong={onGetFullSong}
          isFreeTier={isFreeTier}
          onDeleted={onDeleted}
        />
      ))}
    </div>
  )
}
