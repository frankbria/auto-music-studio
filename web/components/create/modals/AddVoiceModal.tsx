"use client"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { AudioPreview } from "@/components/create/AudioPreview"
import { MOCK_VOICES, type VoiceSelection } from "@/lib/audio-inputs"

/**
 * Add Voice modal (US-16.8): pick a custom voice model to sing the generation.
 * Voice models have no backend yet, so the list comes from MOCK_VOICES; each row
 * has an inline preview and selecting one closes the modal via `onSelect`.
 */
export function AddVoiceModal({
  open,
  onOpenChange,
  onSelect,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (selection: VoiceSelection) => void
}) {
  const voices = MOCK_VOICES

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add voice</DialogTitle>
          <DialogDescription>
            Choose a custom voice model for your generation.
          </DialogDescription>
        </DialogHeader>

        {voices.length === 0 ? (
          <p className="px-2 py-6 text-sm text-muted-foreground">
            No custom voices yet. Train a voice in Settings.
          </p>
        ) : (
          <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
            {voices.map((voice) => (
              <li
                key={voice.id}
                className="flex flex-col gap-2 rounded-lg border p-3"
              >
                <button
                  type="button"
                  onClick={() => {
                    onSelect({ id: voice.id, name: voice.name })
                    onOpenChange(false)
                  }}
                  className="flex flex-col items-start text-left"
                >
                  <span className="text-sm font-medium">{voice.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {voice.description}
                  </span>
                </button>
                <AudioPreview source={voice.previewUrl} />
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
