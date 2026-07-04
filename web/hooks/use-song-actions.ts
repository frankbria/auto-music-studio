"use client"

import { useState } from "react"
import { useRouter } from "next/navigation"

import { useAuth } from "@/hooks/use-auth"
import { downloadClipAudio, type DownloadFormat } from "@/lib/clips"
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

export function useSongActions(clip: Clip) {
  const router = useRouter()
  const { accessToken } = useAuth()
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
    if (action === "publish-toggle") {
      // Optimistic, like SongHeader/ClipCard — the publish route lands in
      // US-17.6; until then the toggle is local feedback only.
      setOptimisticPublic(!isPublic)
    } else if (action === "delete") {
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
      router.push("/")
    } catch {
      // Keep the dialog open so the user can retry or cancel.
      setActionError("Couldn't delete this song. Please try again.")
    } finally {
      setDeleting(false)
    }
  }

  return {
    isPublic,
    activeModal,
    closeModal: () => setActiveModal(null),
    confirmingDelete,
    cancelDelete: () => setConfirmingDelete(false),
    confirmDelete,
    deleting,
    actionError,
    clearActionError: () => setActionError(null),
    handleAction,
    /** SongHeader-compatible publish callback (id, next). */
    togglePublish: (_id: string, next: boolean) => setOptimisticPublic(next),
  }
}
