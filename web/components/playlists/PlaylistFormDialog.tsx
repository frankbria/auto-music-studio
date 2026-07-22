"use client"

import { useState } from "react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"

// Create / rename dialog (US-20.3). One dialog serves both: `initial` seeds the
// fields (rename) or is empty (create). Submit is disabled until the name is
// non-blank; the parent owns persistence via onSubmit.

export type PlaylistFormDialogProps = {
  open: boolean
  mode: "create" | "rename"
  initial?: { name: string; description: string }
  onSubmit: (name: string, description: string) => void
  onOpenChange: (open: boolean) => void
}

export function PlaylistFormDialog({
  open,
  mode,
  initial,
  onSubmit,
  onOpenChange,
}: PlaylistFormDialogProps) {
  const [name, setName] = useState(initial?.name ?? "")
  const [description, setDescription] = useState(initial?.description ?? "")

  // Reset the fields whenever the dialog transitions to open, so a create form
  // starts blank and a rename form shows the current values. This is the "adjust
  // state during render on prop change" pattern (React docs) — resetting here
  // instead of in an effect avoids the set-state-in-effect lint and any flash.
  const [wasOpen, setWasOpen] = useState(open)
  if (open !== wasOpen) {
    setWasOpen(open)
    if (open) {
      setName(initial?.name ?? "")
      setDescription(initial?.description ?? "")
    }
  }

  const canSubmit = name.trim().length > 0
  const isCreate = mode === "create"

  const submit = () => {
    if (!canSubmit) return
    onSubmit(name, description)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isCreate ? "New playlist" : "Rename playlist"}</DialogTitle>
          <DialogDescription>
            {isCreate
              ? "Name your playlist. You can add songs and a cover next."
              : "Update the playlist name or description."}
          </DialogDescription>
        </DialogHeader>

        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="playlist-name">Name</Label>
            <Input
              id="playlist-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="My playlist"
              autoFocus
            />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="playlist-description">Description (optional)</Label>
            <Textarea
              id="playlist-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What's this playlist about?"
              rows={3}
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!canSubmit}>
              {isCreate ? "Create" : "Save"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
