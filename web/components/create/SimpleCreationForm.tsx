"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { Add01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/hooks/use-auth"
import { useGeneration } from "@/hooks/use-generation"
import { useModelSelection } from "@/contexts/model-selection-context"
import { submitGeneration } from "@/lib/generate"
import { InspirationTags } from "@/components/create/InspirationTags"
import { GenerationProgress } from "@/components/create/GenerationProgress"
import { GenerationError } from "@/components/create/GenerationError"
import {
  AudioInputs,
  EMPTY_AUDIO_INPUTS,
  type AudioInputsValue,
} from "@/components/create/AudioInputs"
import type { InspirationSelection } from "@/lib/audio-inputs"

/**
 * The Simple creation form (US-16.1): describe a song in plain language and go.
 * A controlled form whose Create button enables as soon as there's a description
 * or lyrics, then drives the full generation lifecycle (US-16.7) via useGeneration:
 * submit → poll → progress/estimate → clips. `onGenerated` fires once clips exist
 * so the Create page can refresh the workspace panel.
 */
export function SimpleCreationForm({
  onGenerated,
  initialInspiration,
}: {
  onGenerated?: () => void
  /** Pre-attached inspiration (US-20.3 "Use as Inspiration" deep link → chip). */
  initialInspiration?: InspirationSelection
} = {}) {
  const router = useRouter()
  const { accessToken } = useAuth()
  const { models, selectedModel, isLoading: modelLoading } = useModelSelection()
  const generation = useGeneration({ onComplete: onGenerated })

  const [description, setDescription] = useState("")
  const [instrumental, setInstrumental] = useState(false)
  const [lyrics, setLyrics] = useState("")
  const [showLyrics, setShowLyrics] = useState(false)
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  // Attached reference audio / voice / inspiration (US-16.8). Tracked here so
  // Clear all resets them and they persist across Simple/Advanced tab switches.
  const [inputs, setInputs] = useState<AudioInputsValue>(
    initialInspiration
      ? { ...EMPTY_AUDIO_INPUTS, inspiration: initialInspiration }
      : EMPTY_AUDIO_INPUTS
  )
  // Neutral notice for non-generation messages, kept separate from the
  // generation state machine.
  const [notice, setNotice] = useState<string | null>(null)

  // Lyrics only count when the field is open — hiding it shouldn't keep Create
  // enabled (and then submit an empty prompt). Use this one value everywhere.
  const effectiveLyrics = showLyrics ? lyrics : ""

  // Enabled the moment either text field has content — tags and the instrumental
  // toggle don't gate submission (per the acceptance criteria).
  const canSubmit =
    description.trim().length > 0 || effectiveLyrics.trim().length > 0
  const busy =
    generation.state.phase === "submitting" ||
    generation.state.phase === "polling"
  const modelName = models.find((m) => m.key === selectedModel)?.display_name

  async function handleCreate() {
    // Block until the model context settles so a saved default isn't missed.
    if (!canSubmit || busy || modelLoading) return
    if (!accessToken) {
      router.push("/login")
      return
    }
    setNotice(null)
    await generation.submit(
      () =>
        submitGeneration(
          { description, lyrics: effectiveLyrics, instrumental, selectedTags },
          accessToken,
          selectedModel
        ),
      accessToken
    )
  }

  function clearAll() {
    setDescription("")
    setInstrumental(false)
    setLyrics("")
    setShowLyrics(false)
    setSelectedTags([])
    setInputs(EMPTY_AUDIO_INPUTS)
    setNotice(null)
    generation.reset()
  }

  return (
    <div className="flex max-w-2xl flex-col gap-5">
      <div className="flex flex-col gap-2">
        <Label htmlFor="song-description">Song description</Label>
        <Textarea
          id="song-description"
          rows={4}
          placeholder="Describe the song you want to create..."
          value={description}
          onChange={(e) => setDescription(e.target.value)}
        />
      </div>

      {showLyrics && (
        <div className="flex flex-col gap-2">
          <Label htmlFor="song-lyrics">Lyrics</Label>
          <Textarea
            id="song-lyrics"
            rows={4}
            placeholder="Write your lyrics here..."
            value={lyrics}
            onChange={(e) => setLyrics(e.target.value)}
          />
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <AudioInputs
          value={inputs}
          onChange={(patch) => setInputs((v) => ({ ...v, ...patch }))}
          disabled={busy}
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          aria-pressed={showLyrics}
          onClick={() => setShowLyrics((v) => !v)}
        >
          <HugeiconsIcon icon={Add01Icon} data-icon="inline-start" />
          Lyrics
        </Button>
        <div className="ml-auto flex items-center gap-2">
          <Switch
            id="instrumental"
            checked={instrumental}
            onCheckedChange={setInstrumental}
          />
          <Label htmlFor="instrumental">Instrumental</Label>
        </div>
      </div>

      <InspirationTags selectedTags={selectedTags} onChange={setSelectedTags} />

      {notice && (
        <p role="status" className="text-sm text-muted-foreground">
          {notice}
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
        {/* ponytail: inline Clear all — a one-line reset, no component needed. */}
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
