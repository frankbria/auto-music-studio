"use client"

import { useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitAddVocal } from "@/lib/editing"
import type { VoiceSelection } from "@/lib/audio-inputs"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"
import { StyleTextarea } from "./StyleTextarea"
import { VoiceField } from "./VoiceField"

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
  const [voice, setVoice] = useState<VoiceSelection | null>(null)

  const error = lyrics.trim() ? null : "Lyrics are required."
  const canSubmit = !error

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () =>
        submitAddVocal(
          clip.id,
          { lyrics, vocal_style: vocalStyle, voice_model_id: voice?.id },
          accessToken
        ),
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
      onRetry={handleSubmit}
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
      <VoiceField value={voice} onChange={setVoice} />
    </EditModalShell>
  )
}
