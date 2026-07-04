"use client"

import { useState } from "react"

import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group"
import { Slider } from "@/components/ui/slider"
import { Switch } from "@/components/ui/switch"
import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { SPEED_MULTIPLIER_MAX, SPEED_MULTIPLIER_MIN } from "@/lib/constants/editing"
import { submitSpeed } from "@/lib/editing"
import type { SpeedPayload } from "@/lib/editing"
import type { Clip } from "@/lib/workspace-clips"

import { EditModalShell } from "./EditModalShell"

// Speed modal (US-17.3): retime a clip either by a playback multiplier or to a
// target BPM, optionally preserving pitch. Local, credit-free (POST
// /clips/{id}/speed). The backend's SpeedRequest accepts exactly one of
// `multiplier` / `target_bpm`, so the mode toggle decides which single field is
// sent. Target-BPM retiming needs the source BPM, so it is only offered when the
// clip carries BPM metadata.

type SpeedMode = "multiplier" | "bpm"

export function SpeedModal({
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

  const [mode, setMode] = useState<SpeedMode>("multiplier")
  const [multiplier, setMultiplier] = useState(1)
  const [targetBpm, setTargetBpm] = useState("")
  const [preservePitch, setPreservePitch] = useState(true)

  const bpmValue = Number(targetBpm)
  const bpmError =
    mode === "bpm"
      ? targetBpm.trim() === "" || !Number.isFinite(bpmValue) || bpmValue <= 0
        ? "Enter a target BPM greater than 0."
        : null
      : null
  const multiplierError =
    mode === "multiplier" &&
    (multiplier < SPEED_MULTIPLIER_MIN || multiplier > SPEED_MULTIPLIER_MAX)
      ? `Speed must be between ${SPEED_MULTIPLIER_MIN}× and ${SPEED_MULTIPLIER_MAX}×.`
      : null
  const error = multiplierError || bpmError
  const canSubmit = !error

  function handleSubmit() {
    if (!accessToken || error) return
    // Send only the active mode's field so the backend's exactly-one rule holds.
    const payload: SpeedPayload =
      mode === "multiplier"
        ? { multiplier, preserve_pitch: preservePitch }
        : { target_bpm: bpmValue, preserve_pitch: preservePitch }
    void edit.submit(() => submitSpeed(clip.id, payload, accessToken), accessToken)
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
      title="Adjust speed"
      description="Retime this clip without re-generating it."
      state={edit.state}
      onSubmit={handleSubmit}
      canSubmit={canSubmit}
      submitLabel="Apply"
      onRetry={edit.retry}
    >
      <RadioGroup value={mode} onValueChange={(v) => setMode(v as SpeedMode)}>
        <div className="flex items-center gap-2">
          <RadioGroupItem id="speed-mode-multiplier" value="multiplier" />
          <Label htmlFor="speed-mode-multiplier">By multiplier</Label>
        </div>
        <div className="flex items-center gap-2">
          <RadioGroupItem
            id="speed-mode-bpm"
            value="bpm"
            disabled={clip.bpm == null}
          />
          <Label htmlFor="speed-mode-bpm">
            By target BPM
            {clip.bpm == null && (
              <span className="text-xs font-normal text-muted-foreground">
                {" "}
                (needs BPM)
              </span>
            )}
          </Label>
        </div>
      </RadioGroup>

      {mode === "multiplier" ? (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between">
            <Label htmlFor="speed-multiplier">Speed</Label>
            <span className="text-sm tabular-nums text-muted-foreground">
              {multiplier.toFixed(2)}×
            </span>
          </div>
          <Slider
            id="speed-multiplier"
            min={SPEED_MULTIPLIER_MIN}
            max={SPEED_MULTIPLIER_MAX}
            step={0.05}
            value={[multiplier]}
            onValueChange={([v]) => setMultiplier(v)}
          />
        </div>
      ) : (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="speed-target-bpm">Target BPM</Label>
          <Input
            id="speed-target-bpm"
            type="number"
            inputMode="numeric"
            min={1}
            value={targetBpm}
            onChange={(e) => setTargetBpm(e.target.value)}
            placeholder="120"
            aria-invalid={bpmError != null}
          />
          {bpmError && (
            <p className="text-xs text-destructive">{bpmError}</p>
          )}
        </div>
      )}

      <div className="flex items-center justify-between">
        <Label htmlFor="speed-preserve-pitch">Preserve pitch</Label>
        <Switch
          id="speed-preserve-pitch"
          checked={preservePitch}
          onCheckedChange={setPreservePitch}
        />
      </div>
    </EditModalShell>
  )
}
