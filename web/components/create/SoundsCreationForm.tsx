"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/hooks/use-auth"
import { useGeneration } from "@/hooks/use-generation"
import { useModelSelection } from "@/contexts/model-selection-context"
import {
  submitSoundsGeneration,
  validateSounds,
  type SoundsFormData,
} from "@/lib/generate"
import {
  BPM_MAX,
  BPM_MIN,
  KEY_OPTIONS,
  PROMPT_MAX_LENGTH,
} from "@/lib/constants/generation"
import { SELECT_CLASS } from "@/lib/constants/ui"
import { GenerationProgress } from "@/components/create/GenerationProgress"
import { GenerationError } from "@/components/create/GenerationError"

const SOUND_TYPES = [
  { value: "one-shot", label: "One-Shot" },
  { value: "loop", label: "Loop" },
] as const

/**
 * The Sounds creation form (US-16.3): generate short clips — one-shots and loops.
 * Mirrors the Simple/Advanced forms' controlled-state, BFF-submit pattern. The
 * type selector is required (it gates Create and maps to the backend's
 * sound_type); BPM and key apply to loops only, matching the backend rule that
 * one-shots carry no tempo/tonal context. Clip rendering is deferred (as in
 * US-16.1/16.2) — success just reports the job started.
 */
export function SoundsCreationForm({
  onGenerated,
}: { onGenerated?: () => void } = {}) {
  const router = useRouter()
  const { accessToken } = useAuth()
  const { models, selectedModel, isLoading: modelLoading } = useModelSelection()
  const generation = useGeneration({ onComplete: onGenerated })

  const [description, setDescription] = useState("")
  const [soundType, setSoundType] = useState<SoundsFormData["soundType"]>("")
  const [bpmAuto, setBpmAuto] = useState(true)
  const [bpm, setBpm] = useState("")
  const [key, setKey] = useState("")
  // Pre-submit validation message, separate from the generation state machine.
  const [formError, setFormError] = useState<string | null>(null)

  const isLoop = soundType === "loop"

  // A type and a description are both required (the description is the prompt);
  // range validation runs on submit so a bad BPM surfaces a message.
  const canSubmit = soundType !== "" && description.trim().length > 0
  const busy =
    generation.state.phase === "submitting" ||
    generation.state.phase === "polling"
  const modelName = models.find((m) => m.key === selectedModel)?.display_name

  function formData(): SoundsFormData {
    return { description, soundType, bpmAuto, bpm, key }
  }

  async function handleCreate() {
    if (!canSubmit || busy || modelLoading) return
    if (!accessToken) {
      router.push("/login")
      return
    }
    const data = formData()
    const error = validateSounds(data)
    if (error) {
      setFormError(error)
      return
    }
    setFormError(null)
    await generation.submit(
      () => submitSoundsGeneration(data, accessToken, selectedModel),
      accessToken
    )
  }

  function clearAll() {
    setDescription("")
    setSoundType("")
    setBpmAuto(true)
    setBpm("")
    setKey("")
    setFormError(null)
    generation.reset()
  }

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Label htmlFor="sound-description">Sound description</Label>
        <Textarea
          id="sound-description"
          rows={4}
          maxLength={PROMPT_MAX_LENGTH}
          placeholder="Describe the sound you want to create..."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      <div className="flex flex-col gap-2">
        <span className="text-sm font-medium">
          Type <span className="text-destructive">*</span>
        </span>
        <div className="flex gap-1.5" role="group" aria-label="Sound type">
          {SOUND_TYPES.map((type) => (
            <Button
              key={type.value}
              type="button"
              size="sm"
              variant={soundType === type.value ? "default" : "outline"}
              aria-pressed={soundType === type.value}
              onClick={() => setSoundType(type.value)}
            >
              {type.label}
            </Button>
          ))}
        </div>
      </div>

      {/* BPM and key are loop-only: a one-shot is a single hit with no tempo. */}
      {isLoop && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sound-bpm">BPM</Label>
            <div className="flex items-center gap-2">
              <Input
                id="sound-bpm"
                type="number"
                min={BPM_MIN}
                max={BPM_MAX}
                disabled={bpmAuto}
                value={bpm}
                onChange={(e) => setBpm(e.target.value)}
              />
              <div className="flex shrink-0 items-center gap-1.5">
                <Switch
                  id="sound-bpm-auto"
                  checked={bpmAuto}
                  onCheckedChange={setBpmAuto}
                />
                <Label htmlFor="sound-bpm-auto">Auto</Label>
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="sound-key">Key</Label>
            <select
              id="sound-key"
              className={SELECT_CLASS}
              value={key}
              onChange={(e) => setKey(e.target.value)}
            >
              <option value="">Any</option>
              {KEY_OPTIONS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {formError && (
        <p role="alert" className="text-sm text-destructive">
          {formError}
        </p>
      )}
      {generation.state.phase === "polling" && (
        <GenerationProgress
          estimatedSeconds={generation.state.estimatedSeconds}
          modelName={modelName}
          progress={generation.state.progress}
        />
      )}
      {generation.state.phase === "success" && (
        <p role="status" className="text-sm text-muted-foreground">
          Your new clips are ready in the workspace.
        </p>
      )}
      {generation.state.phase === "error" && (
        <GenerationError
          message={generation.state.message}
          onRetry={generation.retry}
          onDismiss={generation.reset}
        />
      )}

      <div className="flex items-center gap-2">
        <Button
          type="button"
          className="w-fit"
          disabled={!canSubmit || busy || modelLoading}
          onClick={handleCreate}
        >
          {busy ? "Creating..." : "Create"}
        </Button>
        {/* ponytail: inline Clear all — resets every Sounds field to its default. */}
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={busy}
          onClick={clearAll}
        >
          Clear all
        </Button>
      </div>
    </div>
  )
}
