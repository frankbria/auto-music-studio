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

// Delete confirmation (US-20.3). No alert-dialog primitive in this repo, so it's
// built on Dialog like DeleteSongDialog. Deleting a playlist doesn't touch the
// songs themselves — only the collection.

export function DeletePlaylistDialog({
  open,
  name,
  onConfirm,
  onOpenChange,
}: {
  open: boolean
  name: string | null
  onConfirm: () => void
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete this playlist?</DialogTitle>
          <DialogDescription>
            &ldquo;{name ?? "Untitled playlist"}&rdquo; will be removed. The songs in
            it are not deleted. This can&apos;t be undone.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="destructive"
            onClick={() => {
              onConfirm()
              onOpenChange(false)
            }}
          >
            Delete
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
