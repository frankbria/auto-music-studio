"use client"

import { useId, useMemo, useState } from "react"

import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { DURATION_MAX } from "@/lib/constants/generation"
import { submitExtend } from "@/lib/editing"
import { parseTimeString, validateTimeField } from "@/lib/editing-validation"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"
import { StyleTextarea } from "./StyleTextarea"
import { TimeDurationInput } from "./TimeDurationInput"

// Extend modal (US-17.3): lengthen a clip from its end or from a chosen
// timestamp, optionally steering the continuation with a style override and
// fresh lyrics. Iterative (POST /clips/{id}/extend) so it consumes a credit.

export function ExtendModal({
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
  const fromPointId = useId()

  const [duration, setDuration] = useState("")
  const [mode, setMode] = useState<"end" | "timestamp">("end")
  const [timestamp, setTimestamp] = useState("")
  const [styleOverride, setStyleOverride] = useState("")
  const [lyrics, setLyrics] = useState("")

  const durationError =
    validateTimeField(duration, "Duration") ||
    ((parseTimeString(duration) ?? 0) <= 0 ? "Duration must be greater than 0." : null)

  const timestampError = useMemo(() => {
    if (mode !== "timestamp") return null
    const fieldError = validateTimeField(timestamp, "Timestamp")
    if (fieldError) return fieldError
    const ms = parseTimeString(timestamp) as number
    if (ms <= 0) return "Timestamp must be greater than 0."
    if (durationMs && ms > durationMs) return "Timestamp can't exceed the clip length."
    return null
  }, [mode, timestamp, durationMs])

  // The backend rejects an extend whose resulting length exceeds the generation
  // cap (iterative.py: from_point + duration > DURATION_MAX). Mirror that here so
  // a near-limit extend fails inline instead of round-tripping a 422.
  const capError = useMemo(() => {
    if (durationError || timestampError) return null
    const fromMs = mode === "timestamp" ? (parseTimeString(timestamp) ?? 0) : durationMs
    const durMs = parseTimeString(duration) ?? 0
    if (durMs <= 0) return null
    return fromMs + durMs > DURATION_MAX * 1000
      ? `The extended clip can't exceed ${DURATION_MAX}s.`
      : null
  }, [durationError, timestampError, mode, timestamp, duration, durationMs])

  const error = durationError || timestampError || capError
  const canSubmit = !error

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () =>
        submitExtend(
          clip.id,
          {
            duration,
            from_point: mode === "timestamp" ? timestamp : "end",
            style_override: styleOverride,
            lyrics,
          },
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
      title="Extend"
      description="Add more music to this clip."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Extend"
      creditHint="Uses 1 credit"
      onRetry={handleSubmit}
    >
      <div className="flex flex-col gap-2">
        <Label id={fromPointId}>Extension point</Label>
        <RadioGroup
          aria-labelledby={fromPointId}
          value={mode}
          onValueChange={(v) => setMode(v as "end" | "timestamp")}
        >
          <div className="flex items-center gap-2">
            <RadioGroupItem value="end" id={`${fromPointId}-end`} />
            <Label htmlFor={`${fromPointId}-end`} className="font-normal">
              From end
            </Label>
          </div>
          <div className="flex items-center gap-2">
            <RadioGroupItem value="timestamp" id={`${fromPointId}-timestamp`} />
            <Label htmlFor={`${fromPointId}-timestamp`} className="font-normal">
              At timestamp
            </Label>
          </div>
        </RadioGroup>
        {mode === "timestamp" && (
          <TimeDurationInput
            label="Timestamp"
            value={timestamp}
            onChange={setTimestamp}
            placeholder="30s"
            error={timestampError}
          />
        )}
      </div>
      <TimeDurationInput
        label="Duration"
        value={duration}
        onChange={setDuration}
        placeholder="30s"
        error={duration ? durationError || capError : null}
      />
      <StyleTextarea
        label="Style override"
        value={styleOverride}
        onChange={setStyleOverride}
        placeholder="Optional — steer the new section's style"
      />
      <StyleTextarea
        label="Lyrics continuation"
        value={lyrics}
        onChange={setLyrics}
        placeholder="Optional — lyrics for the extended section"
        maxLength={5000}
      />
    </EditModalShell>
  )
}
