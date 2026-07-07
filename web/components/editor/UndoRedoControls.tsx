"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Redo02Icon, Undo02Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"

// Undo / redo toolbar for the waveform editor (US-18.4). The keyboard shortcuts
// (Ctrl+Z / Ctrl+Shift+Z) are the other affordance, wired in the parent via
// use-editor-shortcuts. canUndo/canRedo disable each button at its stack
// boundary so the control reflects what's actually possible; `title` surfaces
// the shortcut on hover. Mirrors ZoomControls' shape so the header row is
// visually uniform.

export function UndoRedoControls({
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: {
  onUndo: () => void
  onRedo: () => void
  canUndo: boolean
  canRedo: boolean
}) {
  return (
    <div className="flex items-center gap-1">
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Undo"
        title="Undo (Ctrl+Z)"
        onClick={onUndo}
        disabled={!canUndo}
      >
        <HugeiconsIcon icon={Undo02Icon} />
      </Button>
      <Button
        type="button"
        variant="outline"
        size="icon-sm"
        aria-label="Redo"
        title="Redo (Ctrl+Shift+Z)"
        onClick={onRedo}
        disabled={!canRedo}
      >
        <HugeiconsIcon icon={Redo02Icon} />
      </Button>
    </div>
  )
}
