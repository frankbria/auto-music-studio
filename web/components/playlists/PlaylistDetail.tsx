"use client"

import { useRef, useState } from "react"
import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import {
  Add01Icon,
  ArrowLeft01Icon,
  Copy01Icon,
  Globe02Icon,
  Image01Icon,
  LockIcon,
  MusicNote01Icon,
  SparklesIcon,
  Tick02Icon,
  Upload04Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { AddSongsDialog } from "@/components/playlists/AddSongsDialog"
import { PlaylistCover } from "@/components/playlists/PlaylistCover"
import { PlaylistSongRow } from "@/components/playlists/PlaylistSongRow"
import { usePlaylists } from "@/contexts/playlists-context"
import { buildInspirationHref, buildShareUrl, playlistClips } from "@/lib/playlists"

// Playlist detail page (US-20.3): songs with playback links, add/remove/reorder,
// visibility toggle, cover (auto-mosaic / custom upload), public share link, and
// "Use as Inspiration". All mutations go through the shared PlaylistsProvider store.

export function PlaylistDetail({ playlistId }: { playlistId: string }) {
  const {
    getPlaylist,
    setVisibility,
    addClip,
    removeClip,
    reorderClips,
    setCover,
  } = usePlaylists()
  const playlist = getPlaylist(playlistId)

  const fileInput = useRef<HTMLInputElement>(null)
  const [showAdd, setShowAdd] = useState(false)
  const [copied, setCopied] = useState(false)
  const [dragIndex, setDragIndex] = useState<number | null>(null)

  if (!playlist) {
    return (
      <div className="flex flex-col items-center gap-3 py-20 text-center">
        <p className="font-medium">Playlist not found</p>
        <Button asChild variant="outline">
          <Link href="/playlists">Back to playlists</Link>
        </Button>
      </div>
    )
  }

  const clips = playlistClips(playlist)
  const isPublic = playlist.visibility === "public"

  // Free the previous object URL before replacing/clearing so uploads don't leak
  // blobs. (Unmount without clearing still leaks the last one — acceptable for a
  // session-only mock cover; revisit if covers move to real uploads.)
  const revokePrevCover = () => {
    if (playlist.coverDataUrl?.startsWith("blob:")) {
      URL.revokeObjectURL(playlist.coverDataUrl)
    }
  }

  const onUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      revokePrevCover()
      setCover(playlist.id, URL.createObjectURL(file))
    }
    // Reset so re-selecting the same file fires change again.
    e.target.value = ""
  }

  const clearCover = () => {
    revokePrevCover()
    setCover(playlist.id, null)
  }

  const copyShare = async () => {
    const url = buildShareUrl(window.location.origin, playlist.id)
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard unavailable (e.g. insecure context) — leave the URL visible to copy manually.
    }
  }

  const drop = (to: number) => {
    if (dragIndex != null) reorderClips(playlist.id, dragIndex, to)
    setDragIndex(null)
  }

  return (
    <div className="flex flex-col gap-6 p-8">
      <Link
        href="/playlists"
        className="inline-flex w-fit items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
      >
        <HugeiconsIcon icon={ArrowLeft01Icon} size={16} />
        Playlists
      </Link>

      {/* Header */}
      <div className="flex flex-col gap-6 sm:flex-row sm:items-end">
        <div className="w-40 shrink-0">
          <PlaylistCover playlist={playlist} />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <HugeiconsIcon icon={isPublic ? Globe02Icon : LockIcon} size={12} />
            {isPublic ? "Public" : "Private"} · {clips.length}{" "}
            {clips.length === 1 ? "song" : "songs"}
          </div>
          <h1 className="text-2xl font-semibold">{playlist.name}</h1>
          {playlist.description && (
            <p className="text-sm text-muted-foreground">{playlist.description}</p>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={() => setShowAdd(true)}>
              <HugeiconsIcon icon={Add01Icon} size={16} />
              Add songs
            </Button>
            <Button asChild variant="outline">
              <Link href={buildInspirationHref(playlist)}>
                <HugeiconsIcon icon={SparklesIcon} size={16} />
                Use as Inspiration
              </Link>
            </Button>
            <Button
              variant="outline"
              onClick={() => fileInput.current?.click()}
            >
              <HugeiconsIcon icon={Upload04Icon} size={16} />
              Upload cover
            </Button>
            {playlist.coverDataUrl && (
              <Button variant="ghost" onClick={clearCover}>
                <HugeiconsIcon icon={Image01Icon} size={16} />
                Use mosaic
              </Button>
            )}
            <input
              ref={fileInput}
              type="file"
              accept="image/*"
              className="hidden"
              onChange={onUpload}
              data-testid="cover-upload-input"
            />
          </div>

          {/* Visibility + share */}
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <Switch
                id="playlist-visibility"
                checked={isPublic}
                onCheckedChange={(on) =>
                  setVisibility(playlist.id, on ? "public" : "private")
                }
              />
              <Label htmlFor="playlist-visibility">Public playlist</Label>
            </div>
            {isPublic ? (
              <div className="flex items-center gap-2">
                {/* Origin is client-only, so the server renders the path and the
                    client fills in the full URL — suppress the hydration diff. */}
                <code
                  suppressHydrationWarning
                  className="max-w-xs truncate rounded bg-muted px-2 py-1 text-xs"
                >
                  {buildShareUrl(
                    typeof window !== "undefined" ? window.location.origin : "",
                    playlist.id
                  )}
                </code>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={copyShare}
                  aria-label="Copy share link"
                >
                  <HugeiconsIcon icon={copied ? Tick02Icon : Copy01Icon} size={14} />
                  {copied ? "Copied" : "Copy link"}
                </Button>
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">
                Make this playlist public to get a shareable link.
              </p>
            )}
          </div>
        </div>
      </div>

      {/* Songs */}
      {clips.length === 0 ? (
        <div
          className="flex flex-col items-center gap-3 rounded-lg border border-dashed border-border py-16 text-center"
          data-testid="playlist-songs-empty"
        >
          <HugeiconsIcon
            icon={MusicNote01Icon}
            size={28}
            aria-hidden
            className="text-muted-foreground"
          />
          <p className="font-medium">No songs yet</p>
          <p className="max-w-sm text-sm text-muted-foreground">
            Add songs from the catalog to build out this playlist.
          </p>
          <Button onClick={() => setShowAdd(true)}>
            <HugeiconsIcon icon={Add01Icon} size={16} />
            Add songs
          </Button>
        </div>
      ) : (
        <div className="flex flex-col gap-1" data-testid="playlist-songs">
          {clips.map((clip, index) => (
            <PlaylistSongRow
              key={clip.id}
              clip={clip}
              index={index}
              total={clips.length}
              onMoveUp={() => reorderClips(playlist.id, index, index - 1)}
              onMoveDown={() => reorderClips(playlist.id, index, index + 1)}
              onRemove={() => removeClip(playlist.id, clip.id)}
              dragging={dragIndex === index}
              dragProps={{
                draggable: true,
                onDragStart: () => setDragIndex(index),
                onDragOver: (e) => e.preventDefault(),
                onDrop: () => drop(index),
                onDragEnd: () => setDragIndex(null),
              }}
            />
          ))}
        </div>
      )}

      <AddSongsDialog
        open={showAdd}
        existingIds={playlist.clipIds}
        onAdd={(clipId) => addClip(playlist.id, clipId)}
        onOpenChange={setShowAdd}
      />
    </div>
  )
}
