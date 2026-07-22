"use client"

import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  Delete02Icon,
  Edit02Icon,
  Globe02Icon,
  LockIcon,
  MoreHorizontalIcon,
} from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { PlaylistCover } from "@/components/playlists/PlaylistCover"
import type { Playlist } from "@/lib/playlists"

// Library grid tile (US-20.3). The whole card links to the detail page; the
// overflow menu (rename/delete) sits above the link so its clicks don't navigate.

export function PlaylistCard({
  playlist,
  onRename,
  onDelete,
}: {
  playlist: Playlist
  onRename: (playlist: Playlist) => void
  onDelete: (playlist: Playlist) => void
}) {
  const count = playlist.clipIds.length
  const isPublic = playlist.visibility === "public"

  return (
    <div className="group/card relative flex flex-col gap-2">
      <Link
        href={`/playlists/${playlist.id}`}
        className="flex flex-col gap-2 rounded-lg outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        data-testid="playlist-card"
      >
        <PlaylistCover playlist={playlist} />
        <div className="flex flex-col gap-1">
          <span className="truncate text-sm font-medium" title={playlist.name}>
            {playlist.name}
          </span>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <span>
              {count} {count === 1 ? "song" : "songs"}
            </span>
            <Badge variant="secondary" className="gap-1 text-[10px]">
              <HugeiconsIcon icon={isPublic ? Globe02Icon : LockIcon} size={11} />
              {isPublic ? "Public" : "Private"}
            </Badge>
          </div>
        </div>
      </Link>

      <div className="absolute top-2 right-2 opacity-0 transition-opacity group-hover/card:opacity-100 focus-within:opacity-100">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="secondary"
              size="icon"
              className="size-8"
              aria-label={`Actions for ${playlist.name}`}
            >
              <HugeiconsIcon icon={MoreHorizontalIcon} size={16} />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => onRename(playlist)}>
              <HugeiconsIcon icon={Edit02Icon} size={16} />
              Rename
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={() => onDelete(playlist)}>
              <HugeiconsIcon icon={Delete02Icon} size={16} />
              Delete
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  )
}
