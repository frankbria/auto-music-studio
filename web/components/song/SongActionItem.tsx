"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { LockIcon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { DropdownMenuItem } from "@/components/ui/dropdown-menu"
import {
  isSongActionLocked,
  type SongActionDefinition,
} from "@/lib/song-actions"

// One menu item, rendered from the shared registry (lib/song-actions). Extracted
// from SongActionsMenu in #404: ClipCard hardcoded its own copies of these items
// and badged only one of its Pro ones, so the same action looked free on the card
// and locked on song detail. Anything tier-visible belongs here, not at a call site.

export type SongActionItemProps = {
  action: SongActionDefinition
  /** Overrides the registry label — Publish/Unpublish, "Remix / Edit". */
  label?: string
  isFreeTier: boolean
  /**
   * The clip's stored audio format. A lossless download of a clip already in that
   * format is not a conversion, and the API does not gate it — so neither does the
   * menu. See `isSongActionLocked`.
   */
  nativeFormat?: string | null
  onSelect: () => void
  /** Drop the leading icon — the compact clip-card menus render label-only. */
  hideIcon?: boolean
}

export function SongActionItem({
  action,
  label,
  isFreeTier,
  nativeFormat,
  onSelect,
  hideIcon = false,
}: SongActionItemProps) {
  // US-26.2 AC2: a locked item stays *clickable*. It used to render `disabled`, so
  // clicking a Pro feature did nothing at all — which reads as a broken menu rather than
  // a boundary. The parent turns the click into an upgrade modal.
  const locked = isSongActionLocked(action, { isFreeTier, nativeFormat })

  return (
    <DropdownMenuItem
      variant={action.destructive ? "destructive" : "default"}
      data-locked={locked || undefined}
      onSelect={onSelect}
    >
      {!hideIcon && (
        <HugeiconsIcon
          icon={action.icon}
          size={16}
          className="text-muted-foreground"
        />
      )}
      {label ?? action.label}
      {action.proOnly && (
        <Badge variant="outline" className="ml-auto text-[10px]">
          {locked && <HugeiconsIcon icon={LockIcon} data-icon="inline-start" />}
          Pro
        </Badge>
      )}
      {action.beta && (
        <Badge variant="secondary" className="ml-auto text-[10px]">
          Beta
        </Badge>
      )}
    </DropdownMenuItem>
  )
}
