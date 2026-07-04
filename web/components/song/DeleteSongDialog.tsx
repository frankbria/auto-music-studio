"use client"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"

// US-17.2: confirmation for the action menu's Delete. Built on Dialog (the
// repo has no alert-dialog primitive). A failed delete keeps the dialog open
// with the error so the user can retry or cancel.

export type DeleteSongDialogProps = {
  open: boolean
  title: string | null
  deleting: boolean
  error: string | null
  onCancel: () => void
  onConfirm: () => void
}

export function DeleteSongDialog({
  open,
  title,
  deleting,
  error,
  onCancel,
  onConfirm,
}: DeleteSongDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onCancel()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this song?</DialogTitle>
          <DialogDescription>
            &ldquo;{title ?? "Untitled clip"}&rdquo; and its audio will be
            permanently deleted. This can&apos;t be undone.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={deleting}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={deleting}>
            {deleting ? "Deleting…" : "Delete"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
