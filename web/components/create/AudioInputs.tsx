"use client"

import { useState } from "react"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  MusicNote01Icon,
  Playlist01Icon,
  VoiceIcon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { InputChip } from "@/components/create/InputChip"
import { AddAudioModal } from "@/components/create/modals/AddAudioModal"
import { AddVoiceModal } from "@/components/create/modals/AddVoiceModal"
import { AddInspirationModal } from "@/components/create/modals/AddInspirationModal"
import type {
  AudioSelection,
  InspirationSelection,
  VoiceSelection,
} from "@/lib/audio-inputs"

export type AudioInputsValue = {
  audio: AudioSelection | null
  voice: VoiceSelection | null
  inspiration: InspirationSelection | null
}

export const EMPTY_AUDIO_INPUTS: AudioInputsValue = {
  audio: null,
  voice: null,
  inspiration: null,
}

/**
 * The +Audio / +Voice / +Inspiration controls shared by the Simple and Advanced
 * creation forms (US-16.8). Controlled: the parent owns the selections (so its
 * "Clear all" can reset them and they persist across Simple/Advanced tab
 * switches) and receives patches via `onChange`. Selected inputs render as
 * removable chips; modal open/close is local UI state.
 *
 * ponytail: selections are surfaced to the parent but not yet sent in the
 * generation payload — backend support for reference audio/voice/inspiration is
 * out of scope for this UI story.
 */
export function AudioInputs({
  value,
  onChange,
  disabled,
}: {
  value: AudioInputsValue
  onChange: (patch: Partial<AudioInputsValue>) => void
  disabled?: boolean
}) {
  const [audioOpen, setAudioOpen] = useState(false)
  const [voiceOpen, setVoiceOpen] = useState(false)
  const [inspirationOpen, setInspirationOpen] = useState(false)

  const hasChips = value.audio || value.voice || value.inspiration

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => setAudioOpen(true)}
        >
          <HugeiconsIcon icon={MusicNote01Icon} data-icon="inline-start" />
          Audio
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => setVoiceOpen(true)}
        >
          <HugeiconsIcon icon={VoiceIcon} data-icon="inline-start" />
          Voice
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => setInspirationOpen(true)}
        >
          <HugeiconsIcon icon={Playlist01Icon} data-icon="inline-start" />
          Inspiration
        </Button>
      </div>

      {hasChips && (
        <div
          className="flex flex-wrap items-center gap-2"
          aria-label="Attached inputs"
        >
          {value.audio && (
            <InputChip
              type="audio"
              label={value.audio.label}
              onRemove={() => onChange({ audio: null })}
            />
          )}
          {value.voice && (
            <InputChip
              type="voice"
              label={value.voice.name}
              onRemove={() => onChange({ voice: null })}
            />
          )}
          {value.inspiration && (
            <InputChip
              type="inspiration"
              label={value.inspiration.name}
              onRemove={() => onChange({ inspiration: null })}
            />
          )}
        </div>
      )}

      <AddAudioModal
        open={audioOpen}
        onOpenChange={setAudioOpen}
        onSelect={(audio) => onChange({ audio })}
      />
      <AddVoiceModal
        open={voiceOpen}
        onOpenChange={setVoiceOpen}
        onSelect={(voice) => onChange({ voice })}
      />
      <AddInspirationModal
        open={inspirationOpen}
        onOpenChange={setInspirationOpen}
        onSelect={(inspiration) => onChange({ inspiration })}
      />
    </div>
  )
}
