"use client"

import { useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitAddVocal } from "@/lib/editing"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"
import { StyleTextarea } from "./StyleTextarea"

// Add-vocal modal (US-17.3): layer sung lyrics over a clip
// (POST /clips/{id}/add-vocal). Consumes a credit. A required lyrics field plus
// an optional vocal-style hint.

export function AddVocalModal({
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

  const [lyrics, setLyrics] = useState("")
  const [vocalStyle, setVocalStyle] = useState("")

  const error = lyrics.trim() ? null : "Lyrics are required."
  const canSubmit = !error

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () =>
        submitAddVocal(clip.id, { lyrics, vocal_style: vocalStyle }, accessToken),
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
      title="Add vocal"
      description="Layer sung lyrics over this clip."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Add vocal"
      creditHint="Uses 1 credit"
      onRetry={edit.retry}
    >
      <StyleTextarea
        label="Lyrics"
        value={lyrics}
        onChange={setLyrics}
        maxLength={5000}
        required
        rows={4}
      />
      <StyleTextarea
        label="Vocal style"
        value={vocalStyle}
        onChange={setVocalStyle}
        maxLength={1000}
      />
    </EditModalShell>
  )
}
