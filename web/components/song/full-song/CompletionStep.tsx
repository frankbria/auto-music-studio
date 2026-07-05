"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { CheckmarkCircle01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { formatTime } from "@/lib/clips"

import { SectionPreviewPlayer } from "./SectionPreviewPlayer"

// Step 4 of the wizard (US-17.4): the finished song. Because each accepted
// extend appends to the previous clip, the final clip *is* the last accepted
// result — no separate assembly. It already lives in the workspace; this step
// confirms that and offers to open it on its song-detail page.

export function CompletionStep({
  finalClipId,
  seedTitle,
  totalDuration,
  sectionsCompleted,
  creditsUsed,
  onOpenSongDetail,
  onClose,
}: {
  finalClipId: string
  seedTitle: string
  totalDuration: number
  sectionsCompleted: number
  creditsUsed: number
  onOpenSongDetail: () => void
  onClose: () => void
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 text-sm">
        <HugeiconsIcon
          icon={CheckmarkCircle01Icon}
          className="text-primary"
          data-icon="inline-start"
        />
        <span>Your full song is ready and saved to your workspace.</span>
      </div>

      <SectionPreviewPlayer
        clipId={finalClipId}
        title={seedTitle}
        durationSeconds={totalDuration}
      />

      <dl className="grid grid-cols-3 gap-2 text-center text-sm">
        <div>
          <dt className="text-xs text-muted-foreground">Length</dt>
          <dd className="tabular-nums">{formatTime(totalDuration)}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Sections</dt>
          <dd className="tabular-nums">{sectionsCompleted}</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Credits used</dt>
          <dd className="tabular-nums">{creditsUsed}</dd>
        </div>
      </dl>

      <div className="flex items-center justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          Close
        </Button>
        <Button onClick={onOpenSongDetail}>Open in Song Detail</Button>
      </div>
    </div>
  )
}
