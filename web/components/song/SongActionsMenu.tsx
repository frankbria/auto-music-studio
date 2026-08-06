"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon, Download01Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { SongActionItem } from "@/components/song/SongActionItem"
import {
  SONG_ACTION_GROUPS,
  SONG_DOWNLOAD_ITEMS,
  type SongActionId,
} from "@/lib/song-actions"

// US-17.2: the song-detail full action menu — the hub for every edit, remix,
// audio, export, and manage operation on a song. Purely presentational: it
// renders the shared registry (lib/song-actions) and emits the selected action
// id; the parent (SongDetail via useSongActions) decides whether that means a
// modal, navigation, an inline call, or a download. Keyboard behavior (arrows,
// Escape, type-ahead) comes from the Radix DropdownMenu primitives.

export type SongActionsMenuProps = {
  /** Current visibility; flips the Publish/Unpublish label. */
  isPublic: boolean
  /** Free-tier users see Pro-only actions locked (badge + padlock). */
  isFreeTier: boolean
  /**
   * The clip's stored audio format. A lossless download of a clip already in that
   * format is not a conversion, and the API does not gate it — so neither does the
   * menu. See `isSongActionLocked`.
   */
  nativeFormat?: string | null
  onAction: (action: SongActionId) => void
  /** Actions to omit entirely — e.g. Get Full Song on a clip too long to seed one (US-17.4). */
  hiddenActionIds?: readonly SongActionId[]
}

export function SongActionsMenu({
  isPublic,
  isFreeTier,
  nativeFormat,
  onAction,
  hiddenActionIds,
}: SongActionsMenuProps) {
  const hidden = new Set(hiddenActionIds)
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button size="sm" aria-label="Song actions menu">
          Actions
          <HugeiconsIcon icon={ArrowDown01Icon} data-icon="inline-end" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {SONG_ACTION_GROUPS.map((group, groupIndex) => (
          <DropdownMenuGroup key={group.category} aria-label={group.label}>
            {groupIndex > 0 && <DropdownMenuSeparator />}
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              {group.label}
            </DropdownMenuLabel>
            {group.actions
              .filter((action) => !hidden.has(action.id))
              .map((action) => (
                <SongActionItem
                  key={action.id}
                  action={action}
                  // The registry label is static; the menu shows the state it flips to.
                  label={
                    action.id === "publish-toggle"
                      ? isPublic
                        ? "Unpublish"
                        : "Publish"
                      : undefined
                  }
                  isFreeTier={isFreeTier}
                  nativeFormat={nativeFormat}
                  onSelect={() => onAction(action.id)}
                />
              ))}
            {group.category === "export" && (
              <DropdownMenuSub>
                <DropdownMenuSubTrigger>
                  <HugeiconsIcon
                    icon={Download01Icon}
                    size={16}
                    className="text-muted-foreground"
                  />
                  Download
                </DropdownMenuSubTrigger>
                <DropdownMenuSubContent>
                  {SONG_DOWNLOAD_ITEMS.map((action) => (
                    <SongActionItem
                      key={action.id}
                      action={action}
                      isFreeTier={isFreeTier}
                      nativeFormat={nativeFormat}
                      onSelect={() => onAction(action.id)}
                      hideIcon
                    />
                  ))}
                </DropdownMenuSubContent>
              </DropdownMenuSub>
            )}
          </DropdownMenuGroup>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
