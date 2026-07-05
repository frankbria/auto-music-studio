"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { useAuth } from "@/hooks/use-auth"
import { useFullSongFlow } from "@/hooks/use-full-song-flow"
import {
  DEFAULT_TARGET_DURATION,
  planSections,
  sectionExtendSeconds,
} from "@/lib/song-structure"
import type { Clip } from "@/lib/workspace-clips"

import { CompletionStep } from "./CompletionStep"
import { SectionGenerationStep } from "./SectionGenerationStep"
import { SectionReviewStep } from "./SectionReviewStep"
import { StructurePreviewStep } from "./StructurePreviewStep"

// The Get Full Song wizard (US-17.4). Grows a short seed clip into a full song
// by extending it section-by-section, pausing after each for review. Container
// only: it owns the flow state machine and routes each status to its step. The
// song-detail page reaches it through the SongActionModal dispatch seam; clip
// cards open it directly.

export function FullSongWizardModal({
  clip,
  open,
  onClose,
}: {
  clip: Clip
  open: boolean
  onClose: () => void
}) {
  const router = useRouter()
  const { accessToken } = useAuth()
  const seedDuration = clip.duration ?? 0
  const seedTitle = clip.title ?? "Untitled clip"
  const baseStyle = clip.style_tags.join(", ")

  const flow = useFullSongFlow(clip.id, DEFAULT_TARGET_DURATION)
  const { state } = flow
  const index = state.currentSectionIndex
  const [confirmingCancel, setConfirmingCancel] = useState(false)

  function doClose() {
    setConfirmingCancel(false)
    flow.reset()
    onClose()
  }

  function handleOpenChange(next: boolean) {
    if (next) return
    // Guard against losing an in-flight generation to a stray click/Escape.
    if (state.status === "generating") {
      setConfirmingCancel(true)
      return
    }
    doClose()
  }

  const stepLabel =
    state.status === "planning"
      ? "Review the plan"
      : state.status === "complete"
        ? "Done"
        : `Section ${index + 1} of ${flow.totalSections}`

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Get Full Song</DialogTitle>
          <DialogDescription>{stepLabel}</DialogDescription>
        </DialogHeader>

        {confirmingCancel ? (
          <div className="flex flex-col gap-4">
            <p className="text-sm">
              A section is still generating. Discard the full-song build?
            </p>
            <div className="flex items-center justify-end gap-2">
              <Button
                variant="ghost"
                onClick={() => setConfirmingCancel(false)}
              >
                Keep going
              </Button>
              <Button variant="destructive" onClick={doClose}>
                Discard
              </Button>
            </div>
          </div>
        ) : state.status === "planning" ? (
          <StructurePreviewStep
            seedTitle={seedTitle}
            seedDuration={seedDuration}
            onStart={(target) =>
              flow.beginGeneration(planSections(seedDuration, target), target)
            }
          />
        ) : state.status === "generating" && flow.currentSection ? (
          <SectionGenerationStep
            key={`gen-${index}-${state.regenAttempts[index] ?? 0}`}
            cumulativeClipId={state.cumulativeClipId}
            section={flow.currentSection}
            baseStyle={baseStyle}
            instructions={state.regenerationInstructions}
            accessToken={accessToken}
            sectionNumber={index + 1}
            totalSections={flow.totalSections}
            onComplete={flow.sectionComplete}
          />
        ) : state.status === "reviewing" && flow.currentSection ? (
          <SectionReviewStep
            section={flow.currentSection}
            sectionNumber={index + 1}
            totalSections={flow.totalSections}
            clipId={state.generatedClips[index]}
            seedTitle={seedTitle}
            rejected={state.sectionStatuses[index] === "rejected"}
            regenAttempts={state.regenAttempts[index] ?? 0}
            onAccept={flow.accept}
            onReject={flow.reject}
            onRegenerate={flow.regenerate}
          />
        ) : state.status === "complete" && state.finalClipId ? (
          <CompletionStep
            finalClipId={state.finalClipId}
            seedTitle={seedTitle}
            // The assembled length: the seed plus what each section actually
            // requested (floored), not the raw target the user picked.
            totalDuration={
              seedDuration +
              state.plannedSections.reduce(
                (total, section) => total + sectionExtendSeconds(section),
                0
              )
            }
            sectionsCompleted={flow.totalSections}
            creditsUsed={state.creditsUsed}
            onOpenSongDetail={() => {
              const target = state.finalClipId
              doClose()
              if (target) router.push(`/song/${encodeURIComponent(target)}`)
            }}
            onClose={doClose}
          />
        ) : null}
      </DialogContent>
    </Dialog>
  )
}
