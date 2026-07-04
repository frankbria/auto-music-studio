"use client"

import { useState } from "react"

import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { submitSample } from "@/lib/editing"
import { validateRange } from "@/lib/editing-validation"
import {
  SAMPLE_NUM_CLIPS_MAX,
  SAMPLE_NUM_CLIPS_MIN,
  SAMPLE_ROLES,
  type SampleRole,
} from "@/lib/constants/editing"
import { PROMPT_MAX_LENGTH } from "@/lib/constants/generation"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"
import { RangeSelector } from "./RangeSelector"
import { StyleTextarea } from "./StyleTextarea"

// Sample modal (US-17.3): extract a musical sample (loop bed, hook, etc.) from a
// [start, end] region of a clip, generating 1–4 new clips in the chosen role.
// Iterative (POST /clips/{id}/sample), so it consumes one credit per output clip
// — the footer hint tracks `num_clips` so the cost is clear before submit.

export function SampleModal({
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
  const [role, setRole] = useState<SampleRole>("loop-bed")
  const [prompt, setPrompt] = useState("")
  const [numClips, setNumClips] = useState(SAMPLE_NUM_CLIPS_MIN)

  const rangeError = validateRange(start, end, durationMs || null)
  const promptError = prompt.trim() ? null : "Prompt is required."
  const numClipsError =
    Number.isInteger(numClips) &&
    numClips >= SAMPLE_NUM_CLIPS_MIN &&
    numClips <= SAMPLE_NUM_CLIPS_MAX
      ? null
      : `Number of clips must be between ${SAMPLE_NUM_CLIPS_MIN} and ${SAMPLE_NUM_CLIPS_MAX}.`
  const error = rangeError || promptError || numClipsError
  const canSubmit = !error

  function handleSubmit() {
    if (!accessToken || error) return
    void edit.submit(
      () =>
        submitSample(
          clip.id,
          { start, end, role, prompt, num_clips: numClips },
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
      title="Sample from song"
      description="Extract a sample from a section of this clip."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Create sample"
      creditHint={`Uses ${numClips} credit${numClips > 1 ? "s" : ""}`}
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
        bpm={clip.bpm}
      />
      <div className="flex flex-col gap-2">
        <Label>Role</Label>
        <RadioGroup
          value={role}
          onValueChange={(value) => setRole(value as SampleRole)}
        >
          {SAMPLE_ROLES.map((option) => (
            <div key={option.value} className="flex items-center gap-2">
              <RadioGroupItem value={option.value} id={`sample-role-${option.value}`} />
              <Label htmlFor={`sample-role-${option.value}`} className="font-normal">
                {option.label}
              </Label>
            </div>
          ))}
        </RadioGroup>
      </div>
      <StyleTextarea
        label="Prompt"
        value={prompt}
        onChange={setPrompt}
        maxLength={PROMPT_MAX_LENGTH}
        required
      />
      <div className="flex flex-col gap-2">
        <Label>Number of clips</Label>
        <RadioGroup
          value={String(numClips)}
          onValueChange={(value) => setNumClips(Number(value))}
          className="flex gap-4"
        >
          {Array.from(
            { length: SAMPLE_NUM_CLIPS_MAX - SAMPLE_NUM_CLIPS_MIN + 1 },
            (_, i) => SAMPLE_NUM_CLIPS_MIN + i
          ).map((count) => (
            <div key={count} className="flex items-center gap-2">
              <RadioGroupItem value={String(count)} id={`sample-num-${count}`} />
              <Label htmlFor={`sample-num-${count}`} className="font-normal">
                {count}
              </Label>
            </div>
          ))}
        </RadioGroup>
      </div>
    </EditModalShell>
  )
}
