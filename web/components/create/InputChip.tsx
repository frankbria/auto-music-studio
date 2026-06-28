"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  Cancel01Icon,
  MusicNote01Icon,
  Playlist01Icon,
  VoiceIcon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"

export type InputChipType = "audio" | "voice" | "inspiration"

const ICONS: Record<InputChipType, typeof MusicNote01Icon> = {
  audio: MusicNote01Icon,
  voice: VoiceIcon,
  inspiration: Playlist01Icon,
}

/**
 * A removable badge for a selected creation input (US-16.8): an audio reference,
 * a voice model, or an inspiration playlist. Uses the `secondary` Badge variant
 * to stay visually distinct from the `outline` style-tag pills. The X button
 * fires `onRemove`; the label truncates so long clip/playlist titles don't blow
 * out the row.
 */
export function InputChip({
  type,
  label,
  onRemove,
}: {
  type: InputChipType
  label: string
  onRemove: () => void
}) {
  return (
    <Badge variant="secondary" className="max-w-[14rem] gap-1.5 pr-1">
      <HugeiconsIcon icon={ICONS[type]} className="shrink-0" />
      <span className="truncate" title={label}>
        {label}
      </span>
      <button
        type="button"
        aria-label={`Remove ${label}`}
        onClick={onRemove}
        className="rounded-sm opacity-70 transition-opacity hover:opacity-100"
      >
        <HugeiconsIcon icon={Cancel01Icon} className="size-3" />
      </button>
    </Badge>
  )
}
