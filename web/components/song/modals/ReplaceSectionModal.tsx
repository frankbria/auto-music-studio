"use client"

import { useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitRepaint } from "@/lib/editing"
import { validateRange } from "@/lib/editing-validation"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"
import { RangeSelector } from "./RangeSelector"
import { StyleTextarea } from "./StyleTextarea"

// Replace-section modal (US-17.3): regenerate a [start, end] region of a clip
// from new instructions (POST /clips/{id}/repaint). Consumes a credit. Reuses
// RangeSelector for the region and StyleTextarea for the required replacement
// prompt plus an optional style hint.

export function ReplaceSectionModal({
  clip,
  open,
  onClose,
}: {
  clip: Clip
  open: boolean
  onClose: () => void
}) {
  const { accessToken } = useAuth()
  const edit = useClipEdit()
  const durationMs = clip.duration != null ? Math.round(clip.duration * 1000) : 0

  const [start, setStart] = useState("0s")
  const [end, setEnd] = useState(clip.duration != null ? `${clip.duration}s` : "")
  const [prompt, setPrompt] = useState("")
  const [style, setStyle] = useState("")

  const rangeError = validateRange(start, end, durationMs || null)
  const error = rangeError || (prompt.trim() ? null : "Replacement instructions are required.")
  const canSubmit = !error

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () =>
        submitRepaint(clip.id, { start, end, prompt: prompt.trim(), style }, accessToken),
      accessToken
    )
  }

  function handleOpenChange(next: boolean) {
    if (!next) {
      edit.reset()
      onClose()
    }
  }

  return (
    <EditModalShell
      open={open}
      onOpenChange={handleOpenChange}
      title="Replace section"
      description="Regenerate a section of this clip from new instructions."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Replace"
      creditHint="Uses 1 credit"
      onRetry={handleSubmit}
    >
      <RangeSelector
        clipId={clip.id}
        durationMs={durationMs}
        start={start}
        end={end}
        onChange={({ start: s, end: e }) => {
          setStart(s)
          setEnd(e)
        }}
        bpm={clip.bpm}
      />
      <StyleTextarea
        label="Replacement instructions"
        value={prompt}
        onChange={setPrompt}
        maxLength={2000}
        required
      />
      <StyleTextarea
        label="Style"
        value={style}
        onChange={setStyle}
        maxLength={1000}
      />
    </EditModalShell>
  )
}
