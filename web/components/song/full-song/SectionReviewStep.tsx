"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { STYLE_MAX_LENGTH } from "@/lib/constants/generation"
import type { Section } from "@/lib/song-structure"

import { SectionPreviewPlayer } from "./SectionPreviewPlayer"

// Step 3 of the wizard (US-17.4): preview a generated section and decide. Accept
// advances (the flow extends from this clip next); Reject reveals a note field
// and Regenerate re-runs the section from the last accepted clip with the new
// steering. The regeneration count is surfaced so repeated attempts are visible.

export function SectionReviewStep({
  section,
  sectionNumber,
  totalSections,
  clipId,
  seedTitle,
  rejected,
  regenAttempts,
  onAccept,
  onReject,
  onRegenerate,
}: {
  section: Section
  sectionNumber: number
  totalSections: number
  clipId: string
  seedTitle: string
  rejected: boolean
  regenAttempts: number
  onAccept: () => void
  onReject: () => void
  onRegenerate: (instructions: string) => void
}) {
  const [instructions, setInstructions] = useState("")

  return (
    <div className="flex flex-col gap-4">
      <div className="text-sm">
        <p className="font-medium">
          Section {sectionNumber} of {totalSections}:{" "}
          <span className="capitalize">{section.name}</span>
        </p>
        <p className="text-xs text-muted-foreground">{section.styleHint}</p>
        {regenAttempts > 0 && (
          <p className="text-xs text-muted-foreground">
            Regenerated {regenAttempts}{" "}
            {regenAttempts === 1 ? "time" : "times"}
          </p>
        )}
      </div>

      <SectionPreviewPlayer
        clipId={clipId}
        title={`${seedTitle} — ${section.name}`}
        durationSeconds={section.durationSeconds}
      />

      {rejected ? (
        <div className="flex flex-col gap-2">
          <Label htmlFor="full-song-regen">What should change?</Label>
          <Textarea
            id="full-song-regen"
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder="Optional — e.g. more energy, add a guitar lead"
            rows={2}
            maxLength={STYLE_MAX_LENGTH}
          />
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" onClick={onAccept}>
              Keep it anyway
            </Button>
            <Button onClick={() => onRegenerate(instructions)}>Regenerate</Button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onReject}>
            Reject
          </Button>
          <Button onClick={onAccept}>Accept</Button>
        </div>
      )}
    </div>
  )
}
