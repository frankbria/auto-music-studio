"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/hooks/use-auth"
import { submitSoundsGeneration, validateSounds, type SoundsFormData } from "@/lib/generate"
import { BPM_MAX, BPM_MIN, KEY_OPTIONS, PROMPT_MAX_LENGTH } from "@/lib/constants/generation"
import { SELECT_CLASS } from "@/lib/constants/ui"

type Status =
  | { kind: "idle" }
  | { kind: "info"; message: string }
  | { kind: "success"; message: string }
  | { kind: "error"; message: string }

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
export function SoundsCreationForm() {
  const router = useRouter()
  const { accessToken } = useAuth()

  const [description, setDescription] = useState("")
  const [soundType, setSoundType] = useState<SoundsFormData["soundType"]>("")
  const [bpmAuto, setBpmAuto] = useState(true)
  const [bpm, setBpm] = useState("")
  const [key, setKey] = useState("")
  const [status, setStatus] = useState<Status>({ kind: "idle" })
  const [isSubmitting, setIsSubmitting] = useState(false)

  const isLoop = soundType === "loop"

  // A type and a description are both required (the description is the prompt);
  // range validation runs on submit so a bad BPM surfaces a message.
  const canSubmit = soundType !== "" && description.trim().length > 0

  function formData(): SoundsFormData {
    return { description, soundType, bpmAuto, bpm, key }
  }

  async function handleCreate() {
    if (!canSubmit || isSubmitting) return
    if (!accessToken) {
      router.push("/login")
      return
    }
    const data = formData()
    const error = validateSounds(data)
    if (error) {
      setStatus({ kind: "error", message: error })
      return
    }
    setIsSubmitting(true)
    try {
      const result = await submitSoundsGeneration(data, accessToken)
      switch (result.status) {
        case "accepted":
          setStatus({
            kind: "success",
            message: "Generation started. We'll let you know when it's ready.",
          })
          break
        case "unauthorized":
          router.push("/login")
          break
        case "invalid":
        case "error":
          setStatus({ kind: "error", message: result.detail })
          break
      }
    } finally {
      setIsSubmitting(false)
    }
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
                <Switch id="sound-bpm-auto" checked={bpmAuto} onCheckedChange={setBpmAuto} />
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

      {(status.kind === "info" || status.kind === "success") && (
        <p role="status" className="text-sm text-muted-foreground">
          {status.message}
        </p>
      )}
      {status.kind === "error" && (
        <p role="alert" className="text-sm text-destructive">
          {status.message}
        </p>
      )}

      <Button
        type="button"
        className="w-fit"
        disabled={!canSubmit || isSubmitting}
        onClick={handleCreate}
      >
        {isSubmitting ? "Creating..." : "Create"}
      </Button>
    </div>
  )
}
