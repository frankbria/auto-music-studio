"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import { VoiceIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { InputChip } from "@/components/create/InputChip"
import { AddVoiceModal } from "@/components/create/modals/AddVoiceModal"
import type { VoiceSelection } from "@/lib/audio-inputs"

/**
 * Attach one of the musician's trained voices to a clip-scoped generation (US-25.4) —
 * the Cover, Add Vocal and Extend modals. The Simple/Advanced forms get the same
 * capability through `<AudioInputs>`; this is the single-purpose version for modals
 * that have no audio or inspiration slots.
 *
 * Removing the chip clears the selection, and the generation reverts to the model's
 * own voice.
 */
export function VoiceField({
  value,
  onChange,
  disabled,
}: {
  value: VoiceSelection | null
  onChange: (voice: VoiceSelection | null) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)

  return (
    <div className="flex flex-col gap-2">
      <Label>Voice</Label>
      {value ? (
        <div className="flex flex-wrap items-center gap-2">
          <InputChip
            type="voice"
            label={value.name}
            onRemove={() => onChange(null)}
          />
        </div>
      ) : (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="w-fit"
          disabled={disabled}
          onClick={() => setOpen(true)}
        >
          <HugeiconsIcon icon={VoiceIcon} data-icon="inline-start" />
          Add voice
        </Button>
      )}

      <AddVoiceModal open={open} onOpenChange={setOpen} onSelect={onChange} />
    </div>
  )
}
