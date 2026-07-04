"use client"

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { findSongAction, type SongActionId } from "@/lib/song-actions"

// US-17.2: placeholder container for the modal-workflow actions. The action
// menu dispatches into here so every menu item already opens its own modal;
// the real workflow content (prompts, options, submission) lands with
// US-17.3+ story by story.

export type SongActionModalProps = {
  /** The modal-workflow action to show, or null when closed. */
  action: SongActionId | null
  onClose: () => void
}

export function SongActionModal({ action, onClose }: SongActionModalProps) {
  const definition = action ? findSongAction(action) : null

  return (
    <Dialog
      open={definition != null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{definition?.label}</DialogTitle>
          <DialogDescription>
            This workflow isn&apos;t available yet — it arrives with an upcoming
            update.
          </DialogDescription>
        </DialogHeader>
      </DialogContent>
    </Dialog>
  )
}
