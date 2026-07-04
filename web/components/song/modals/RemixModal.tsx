"use client"

import { useMemo, useState } from "react"

import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitRemix } from "@/lib/editing"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"
import { StyleTextarea } from "./StyleTextarea"

// Remix modal (US-17.3): re-generate a clip in a new style while keeping its
// musical bones. Iterative and credit-consuming (POST /clips/{id}/remix). The
// backend's RemixRequest requires a non-empty `style`, so submit is blocked
// until one is entered.

export function RemixModal({
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

  const error = style.trim() === "" ? "A new style is required." : null
  const canSubmit = useMemo(() => !error, [error])

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () => submitRemix(clip.id, { style }, accessToken),
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
      title="Remix"
      description="Re-imagine this clip in a new style."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Remix"
      creditHint="Uses 1 credit"
      onRetry={edit.retry}
    >
      <StyleTextarea
        label="New style"
        value={style}
        onChange={setStyle}
        placeholder="e.g. 80s synthwave, dreamy pads"
        required
      />
    </EditModalShell>
  )
}
