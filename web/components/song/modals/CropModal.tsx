"use client"

import { useState } from "react"

import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitCrop } from "@/lib/editing"
import { validateRange, validateTimeField } from "@/lib/editing-validation"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"
import { RangeSelector } from "./RangeSelector"
import { TimeDurationInput } from "./TimeDurationInput"

// Crop modal (US-17.3): trim a clip to a [start, end] range with optional fades
// and beat snapping. Local, credit-free (POST /clips/{id}/crop). Snap-to-beat is
// only offered when the clip carries BPM metadata (the backend needs it).

export function CropModal({
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
  const [fadeIn, setFadeIn] = useState("0s")
  const [fadeOut, setFadeOut] = useState("0s")
  const [snapToBeat, setSnapToBeat] = useState(false)

  const rangeError = validateRange(start, end, durationMs || null)
  const fadeInError = validateTimeField(fadeIn, "Fade in")
  const fadeOutError = validateTimeField(fadeOut, "Fade out")
  const error = rangeError || fadeInError || fadeOutError
  const canSubmit = !error

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () =>
        submitCrop(
          clip.id,
          { start, end, fade_in: fadeIn, fade_out: fadeOut, snap_to_beat: snapToBeat },
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
      title="Crop"
      description="Trim this clip to a section."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Crop"
      onRetry={edit.retry}
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
        snapToBeat={snapToBeat}
        bpm={clip.bpm}
      />
      <div className="grid grid-cols-2 gap-3">
        <TimeDurationInput
          label="Fade in"
          value={fadeIn}
          onChange={setFadeIn}
          placeholder="0s"
          error={fadeInError}
        />
        <TimeDurationInput
          label="Fade out"
          value={fadeOut}
          onChange={setFadeOut}
          placeholder="0s"
          error={fadeOutError}
        />
      </div>
      <div className="flex items-center justify-between">
        <Label htmlFor="crop-snap">
          Snap to beat
          {clip.bpm == null && (
            <span className="text-xs font-normal text-muted-foreground">
              {" "}
              (needs BPM)
            </span>
          )}
        </Label>
        <Switch
          id="crop-snap"
          checked={snapToBeat}
          onCheckedChange={setSnapToBeat}
          disabled={clip.bpm == null}
        />
      </div>
    </EditModalShell>
  )
}
