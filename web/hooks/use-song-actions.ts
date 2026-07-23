"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import {
  downloadClipAudio,
  updateClipVisibility,
  type DownloadFormat,
} from "@/lib/clips"
import { submitRemaster } from "@/lib/editing"
import { findSongAction, type SongActionId } from "@/lib/song-actions"
import { visibilityOf, type Clip, type Visibility } from "@/lib/workspace-clips"

// US-17.2: dispatch for the full action menu. Routes a selected action to its
// workflow: navigation (editor/studio), a workflow modal (content lands in
// US-17.3+), a file download, or an inline operation (the US-17.6 publish
// toggle, extended to the tri-state Private/Unlisted/Public picker in
// US-20.7 — optimistic with real persistence + rollback — and delete).

/** Which publish requirements a clip is missing, for the guard prompt (US-17.6). */
export type PublishGuard = {
  missingTitle: boolean
  missingStyleTags: boolean
}

/** Compute the publish guard for a clip; `null` when it's ready to go public. */
function publishGuardFor(clip: Clip): PublishGuard | null {
  const missingTitle = !clip.title?.trim()
  const missingStyleTags = clip.style_tags.length === 0
  return missingTitle || missingStyleTags
    ? { missingTitle, missingStyleTags }
    : null
}

const DOWNLOAD_FORMAT: Partial<Record<SongActionId, DownloadFormat>> = {
  "download-mp3": "mp3",
  "download-wav": "wav",
  "download-flac": "flac",
}

export type UseSongActionsOptions = {
  /**
   * Where to go after a successful delete. Song detail navigates home (the song
   * is gone); the clip list (US-17.5) passes a callback to drop the card in place
   * instead. Defaults to navigating to `/`.
   */
  onDeleted?: (id: string) => void
}

export function useSongActions(clip: Clip, { onDeleted }: UseSongActionsOptions = {}) {
  const router = useRouter()
  const { accessToken } = useAuth()
  const remaster = useClipEdit()
  const [activeModal, setActiveModal] = useState<SongActionId | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [optimisticVisibility, setOptimisticVisibility] = useState<Visibility | null>(
    null
  )
  // Set when going public is blocked (client guard) or rejected (server 422);
  // drives the PublishGuardPrompt. Null means no prompt. Unlisted has no
  // requirements, so it never sets this.
  const [publishGuard, setPublishGuard] = useState<PublishGuard | null>(null)

  const visibility = optimisticVisibility ?? visibilityOf(clip)
  const isPublic = visibility === "public"

  function handleAction(action: SongActionId) {
    const workflow = findSongAction(action)?.workflow
    if (workflow === "navigation") {
      // open-editor → the waveform editor (US-18.1); open-studio → the studio.
      const id = encodeURIComponent(clip.id)
      router.push(action === "open-editor" ? `/editor/${id}` : `/studio?song=${id}`)
      return
    }
    if (workflow === "modal") {
      setActiveModal(action)
      return
    }
    if (workflow === "download") {
      const format = DOWNLOAD_FORMAT[action]
      if (!format || !accessToken) return
      void downloadClipAudio(clip.id, format, accessToken, clip.title).then(
        (ok) => {
          if (!ok) setActionError("Couldn't download this song. Please try again.")
        }
      )
      return
    }
    // Inline actions.
    if (action === "remaster") {
      // One-click remaster (US-17.3): submit immediately with the default -14
      // LUFS streaming target and drive progress inline — no modal.
      if (!accessToken) return
      // Ignore repeat clicks while a remaster is already running, so we don't
      // enqueue a duplicate job and orphan the first (its poll would be dropped).
      if (
        remaster.state.phase === "submitting" ||
        remaster.state.phase === "polling"
      ) {
        return
      }
      void remaster.submit(
        () => submitRemaster(clip.id, {}, accessToken),
        accessToken
      )
    } else if (action === "publish-toggle") {
      void setVisibility(isPublic ? "private" : "public")
    } else if (action === "delete") {
      // Start the confirmation clean — actionError is shared with the download
      // flow, so a prior download failure must not show up in this dialog.
      setActionError(null)
      setConfirmingDelete(true)
    }
  }

  /**
   * Change the clip's visibility with optimistic UI and rollback (US-17.6,
   * tri-state in US-20.7). Only going "public" is guarded client-side (needs
   * a title + a style tag), so the prompt shows before any request; a server
   * 422 (fields changed since load) rolls back and prompts too. Private and
   * unlisted have no requirements. Other failures roll back and surface an
   * error.
   */
  async function setVisibility(next: Visibility) {
    if (!accessToken) return
    if (next === "public") {
      const guard = publishGuardFor(clip)
      if (guard) {
        setPublishGuard(guard)
        return
      }
    }
    const prev = visibility
    setOptimisticVisibility(next)
    setActionError(null)
    const result = await updateClipVisibility(clip.id, next, accessToken)
    if (!result.ok) {
      setOptimisticVisibility(prev) // rollback
      // Prefer the client-side guard prompt, which names the missing fields.
      // But a server 422 can win a race where local `clip` still looks ready
      // (fields changed since load); recomputing the guard would then be
      // all-false and render an empty prompt, so fall back to the server's
      // specific message instead.
      const guard = result.guardFailed ? publishGuardFor(clip) : null
      if (guard) {
        setPublishGuard(guard)
      } else {
        setActionError(result.message)
      }
    }
  }

  async function confirmDelete() {
    if (!accessToken) return
    setDeleting(true)
    setActionError(null)
    try {
      const res = await fetch(`/api/clips/${encodeURIComponent(clip.id)}`, {
        method: "DELETE",
        headers: { authorization: `Bearer ${accessToken}` },
      })
      if (res.status !== 204) throw new Error(`delete failed (${res.status})`)
      if (onDeleted) {
        // List context: the card is dropped by an async refetch, so close the
        // dialog now — otherwise it lingers with a live Delete button on an
        // already-deleted clip and a second click fires a redundant DELETE.
        onDeleted(clip.id)
        setConfirmingDelete(false)
      } else {
        // Song-detail context: navigating home unmounts the dialog.
        router.push("/")
      }
    } catch {
      // Keep the dialog open so the user can retry or cancel.
      setActionError("Couldn't delete this song. Please try again.")
    } finally {
      setDeleting(false)
    }
  }

  return {
    /** Tri-state visibility (US-20.7): "private" | "unlisted" | "public". */
    visibility,
    /** Back-compat derived flag: `visibility === "public"`. */
    isPublic,
    /** One-click remaster lifecycle (US-17.3); drives the inline progress line. */
    remasterState: remaster.state,
    dismissRemaster: remaster.reset,
    activeModal,
    closeModal: () => setActiveModal(null),
    confirmingDelete,
    // Clear the delete error too, so a failed-then-cancelled delete doesn't
    // linger as a stale below-menu alert (actionError is shared with download).
    cancelDelete: () => {
      setActionError(null)
      setConfirmingDelete(false)
    },
    confirmDelete,
    deleting,
    actionError,
    clearActionError: () => setActionError(null),
    handleAction,
    /** Set the clip's visibility directly (US-20.7 picker). Persists + guards. */
    setVisibility,
    /**
     * Back-compat two-state callback (SongHeader/ClipCard's old boolean
     * shape). Maps `next` onto "public"/"private" via `setVisibility`.
     */
    togglePublish: (_id: string, next: boolean) =>
      void setVisibility(next ? "public" : "private"),
    /** Non-null while the publish guard prompt should show; names what's missing. */
    publishGuard,
    dismissPublishGuard: () => setPublishGuard(null),
  }
}
