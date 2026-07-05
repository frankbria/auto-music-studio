"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import { useAuth } from "@/hooks/use-auth"
import { useClipEdit } from "@/hooks/use-clip-edit"
import { downloadClipAudio, type DownloadFormat } from "@/lib/clips"
import { submitRemaster } from "@/lib/editing"
import { findSongAction, type SongActionId } from "@/lib/song-actions"
import type { Clip } from "@/lib/workspace-clips"

// US-17.2: dispatch for the full action menu. Routes a selected action to its
// workflow: navigation (editor/studio), a workflow modal (content lands in
// US-17.3+), a file download, or an inline operation (optimistic publish
// toggle — persistence lands with US-17.6 — and delete-with-confirmation).

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
  const [optimisticPublic, setOptimisticPublic] = useState<boolean | null>(null)

  const isPublic = optimisticPublic ?? clip.is_public

  function handleAction(action: SongActionId) {
    const workflow = findSongAction(action)?.workflow
    if (workflow === "navigation") {
      // Only open-studio navigates today; open-editor joins when the editor
      // page ships (US-18) and its registry entry flips back to navigation.
      router.push(`/studio?song=${encodeURIComponent(clip.id)}`)
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
      // Optimistic, like SongHeader/ClipCard — the publish route lands in
      // US-17.6; until then the toggle is local feedback only.
      setOptimisticPublic(!isPublic)
    } else if (action === "delete") {
      // Start the confirmation clean — actionError is shared with the download
      // flow, so a prior download failure must not show up in this dialog.
      setActionError(null)
      setConfirmingDelete(true)
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
    /** SongHeader-compatible publish callback (id, next). */
    togglePublish: (_id: string, next: boolean) => setOptimisticPublic(next),
  }
}
