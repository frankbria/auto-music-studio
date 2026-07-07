"use client"

import { useState } from "react"

import { EditModalShell } from "@/components/song/modals/EditModalShell"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import type { ClipAudio } from "@/lib/audio-peaks"
import { saveClipVersion } from "@/lib/editing"
import type { EditOperation } from "@/lib/waveform-edit"
import { encodeWav } from "@/lib/wav-encode"

// "Save as new version" modal for the waveform editor (US-18.4). Non-destructive
// editing means the edited audio only lives in the browser, so this encodes it
// to a WAV and uploads it as a new clip (with the source as parent) via
// useClipEdit — the same submit → poll → "View the new clip" lifecycle every
// other editing modal uses. The operation log rides along as provenance.

export function SaveVersionModal({
  clipId,
  audio,
  operations,
  open,
  onClose,
}: {
  clipId: string
  audio: ClipAudio
  operations: EditOperation[]
  open: boolean
  onClose: () => void
}) {
  const { accessToken } = useAuth()
  const edit = useClipEdit()
  const [title, setTitle] = useState("")

  // Nothing to save with no edits applied; the parent already hides the entry
  // point until the clip is dirty, but guard here too.
  const canSubmit = accessToken != null && operations.length > 0

  function handleSubmit() {
    if (!accessToken || operations.length === 0) return
    void edit.submit(
      () =>
        saveClipVersion(clipId, encodeWav(audio), { title, operations }, accessToken),
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
      title="Save as new version"
      description="Save your edits as a new clip. The original clip is left unchanged."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Save version"
      onRetry={handleSubmit}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="version-title">Title (optional)</Label>
        <Input
          id="version-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="e.g. Radio edit"
          maxLength={200}
        />
        <p className="text-xs text-muted-foreground">
          {operations.length} edit{operations.length === 1 ? "" : "s"} will be saved.
        </p>
      </div>
    </EditModalShell>
  )
}
