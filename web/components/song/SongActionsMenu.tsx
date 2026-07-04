"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  ArrowDown01Icon,
  Download01Icon,
  LockIcon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import {
  SONG_ACTION_GROUPS,
  SONG_DOWNLOAD_ITEMS,
  type SongActionDefinition,
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
  /** Free-tier users see Pro-only actions locked (badge + lock, disabled). */
  isFreeTier: boolean
  onAction: (action: SongActionId) => void
}

export function SongActionsMenu({
  isPublic,
  isFreeTier,
  onAction,
}: SongActionsMenuProps) {
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
            {group.actions.map((action) => (
              <ActionItem
                key={action.id}
                action={action}
                isPublic={isPublic}
                isFreeTier={isFreeTier}
                onAction={onAction}
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
                    <ActionItem
                      key={action.id}
                      action={action}
                      isPublic={isPublic}
                      isFreeTier={isFreeTier}
                      onAction={onAction}
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

function ActionItem({
  action,
  isPublic,
  isFreeTier,
  onAction,
  hideIcon = false,
}: {
  action: SongActionDefinition
  isPublic: boolean
  isFreeTier: boolean
  onAction: (action: SongActionId) => void
  hideIcon?: boolean
}) {
  const locked = !!action.proOnly && isFreeTier
  const label =
    action.id === "publish-toggle"
      ? isPublic
        ? "Unpublish"
        : "Publish"
      : action.label

  return (
    <DropdownMenuItem
      variant={action.destructive ? "destructive" : "default"}
      disabled={locked}
      onSelect={() => onAction(action.id)}
    >
      {!hideIcon && (
        <HugeiconsIcon
          icon={action.icon}
          size={16}
          className="text-muted-foreground"
        />
      )}
      {label}
      {action.proOnly && (
        <Badge variant="outline" className="ml-auto text-[10px]">
          {locked && <HugeiconsIcon icon={LockIcon} data-icon="inline-start" />}
          Pro
        </Badge>
      )}
    </DropdownMenuItem>
  )
}
