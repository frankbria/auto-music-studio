"use client"

import { useState } from "react"

import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitMashup } from "@/lib/editing"
import {
  BLEND_MODES,
  MASHUP_CLIPS_MAX,
  MASHUP_CLIPS_MIN,
  type BlendMode,
} from "@/lib/constants/editing"
import type { Clip } from "@/lib/workspace-clips"

import { ClipMultiSelector } from "./ClipMultiSelector"
import { EditModalShell } from "./EditModalShell"
import { StyleTextarea } from "./StyleTextarea"

// Mashup modal (US-17.3): combine 2–8 clips from the workspace into a new clip.
// The current clip seeds the selection as the primary (first) source. Iterative
// (POST /api/mashup — note: no clip id in the path), so it consumes one credit.

export function MashupModal({
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

  const [selected, setSelected] = useState<string[]>([clip.id])
  const [blendMode, setBlendMode] = useState<BlendMode>("layered")
  const [style, setStyle] = useState("")

  const unique = new Set(selected).size === selected.length
  const error =
    selected.length < MASHUP_CLIPS_MIN
      ? `Select at least ${MASHUP_CLIPS_MIN} clips.`
      : selected.length > MASHUP_CLIPS_MAX
        ? `Select at most ${MASHUP_CLIPS_MAX} clips.`
        : !unique
          ? "Clips must be unique."
          : null
  const canSubmit = !error

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () =>
        submitMashup(
          { clip_ids: selected, blend_mode: blendMode, style },
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
      title="Mashup"
      description="Combine several clips into a new one."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Create mashup"
      creditHint="Uses 1 credit"
      onRetry={edit.retry}
    >
      <ClipMultiSelector
        workspaceId={clip.workspace_id}
        selected={selected}
        onChange={setSelected}
      />
      <div className="flex flex-col gap-2">
        <Label>Blend mode</Label>
        <RadioGroup
          value={blendMode}
          onValueChange={(value) => setBlendMode(value as BlendMode)}
        >
          {BLEND_MODES.map((option) => (
            <div key={option.value} className="flex items-center gap-2">
              <RadioGroupItem value={option.value} id={`mashup-blend-${option.value}`} />
              <Label htmlFor={`mashup-blend-${option.value}`} className="font-normal">
                {option.label}
              </Label>
            </div>
          ))}
        </RadioGroup>
      </div>
      <StyleTextarea label="Style override" value={style} onChange={setStyle} />
    </EditModalShell>
  )
}
