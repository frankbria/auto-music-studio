"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { AudioPreview } from "@/components/create/AudioPreview"
import { useAuth } from "@/hooks/use-auth"
import { useVoiceModels } from "@/hooks/use-voice-models"
import { fetchVoicePreview, type VoiceModelSummary } from "@/lib/voice-models"
import type { VoiceSelection } from "@/lib/audio-inputs"

/**
 * Add Voice modal (US-16.8, wired to the real library in US-25.4): pick one of the
 * musician's trained voices to sing the generation.
 *
 * Only `ready` voices are offered — one still training has no weights to generate
 * with, and the backend refuses it, so offering it would just be a dead end. The
 * preview is a *reference recording*, fetched on demand: a trained LoRA has no sample
 * of its own, and rendering one would cost a GPU run per browse.
 */
function VoiceRow({
  model,
  onSelect,
}: {
  model: VoiceModelSummary
  onSelect: (selection: VoiceSelection) => void
}) {
  const { accessToken } = useAuth()
  const [preview, setPreview] = useState<Blob | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function loadPreview() {
    if (!accessToken) return
    setLoading(true)
    setPreviewError(null)
    try {
      setPreview(await fetchVoicePreview(model.id, accessToken))
    } catch {
      setPreviewError("No preview available for this voice.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex items-start justify-between gap-2">
        <button
          type="button"
          onClick={() => onSelect({ id: model.id, name: model.name })}
          className="flex flex-col items-start text-left"
        >
          <span className="text-sm font-medium">{model.name}</span>
          <span className="text-xs text-muted-foreground">
            {model.description ??
              `Trained from ${model.reference_count} recording${model.reference_count === 1 ? "" : "s"}`}
          </span>
        </button>
        {!preview && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={loading}
            onClick={loadPreview}
          >
            {loading ? "Loading…" : "Preview"}
          </Button>
        )}
      </div>
      {preview && <AudioPreview source={preview} label={model.name} />}
      {previewError && (
        <p className="text-xs text-muted-foreground">{previewError}</p>
      )}
    </li>
  )
}

export function AddVoiceModal({
  open,
  onOpenChange,
  onSelect,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (selection: VoiceSelection) => void
}) {
  const { state } = useVoiceModels()
  const ready =
    state.phase === "ready"
      ? state.models.filter((m) => m.status === "ready")
      : []

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add voice</DialogTitle>
          <DialogDescription>
            Choose one of your trained voices for this generation.
          </DialogDescription>
        </DialogHeader>

        {state.phase === "loading" && (
          <p className="px-2 py-6 text-sm text-muted-foreground">
            Loading your voices…
          </p>
        )}
        {state.phase === "signed-out" && (
          <p className="px-2 py-6 text-sm text-muted-foreground">
            Sign in to use your custom voices.
          </p>
        )}
        {state.phase === "error" && (
          <p className="px-2 py-6 text-sm text-destructive">{state.message}</p>
        )}
        {state.phase === "ready" &&
          (ready.length === 0 ? (
            <p className="px-2 py-6 text-sm text-muted-foreground">
              No voices are ready yet. Train one in Settings.
            </p>
          ) : (
            <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
              {ready.map((model) => (
                <VoiceRow
                  key={model.id}
                  model={model}
                  onSelect={(selection) => {
                    onSelect(selection)
                    onOpenChange(false)
                  }}
                />
              ))}
            </ul>
          ))}
      </DialogContent>
    </Dialog>
  )
}
