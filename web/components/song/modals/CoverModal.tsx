"use client"

import { useMemo, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitCover } from "@/lib/editing"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"
import { StyleTextarea } from "./StyleTextarea"

// Cover modal (US-17.3): re-record a clip in a new target style, optionally
// swapping in fresh lyrics. Iterative (POST /clips/{id}/cover) so it consumes a
// credit.

export function CoverModal({
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

  const [style, setStyle] = useState("")
  const [lyricsOverride, setLyricsOverride] = useState("")

  const error = !style.trim() ? "Target style is required." : null
  const canSubmit = useMemo(() => !error, [error])

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () =>
        submitCover(
          clip.id,
          { style, lyrics_override: lyricsOverride },
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
      title="Cover"
      description="Re-record this clip in a new style."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Create cover"
      creditHint="Uses 1 credit"
      onRetry={edit.retry}
    >
      <StyleTextarea
        label="Target style"
        value={style}
        onChange={setStyle}
        placeholder="e.g. acoustic ballad, synthwave, jazz trio"
        required
      />
      <StyleTextarea
        label="Lyrics override"
        value={lyricsOverride}
        onChange={setLyricsOverride}
        placeholder="Optional — replace the lyrics for the cover"
        maxLength={5000}
      />
    </EditModalShell>
  )
}
