"use client"

import { useEffect, useRef } from "react"

// Keyboard shortcuts for the waveform editor: Ctrl/Cmd+X/C/V and
// Delete/Backspace → cut / copy / paste / delete (US-18.2); Ctrl/Cmd+Z → undo
// and Ctrl/Cmd+Shift+Z (or Ctrl+Y) → redo (US-18.4). A single window keydown
// listener attached once; the latest actions are read through a ref (same
// pattern as the canvas's wheel handler) so re-renders don't re-bind. Ignores
// keystrokes aimed at a text field so typing elsewhere isn't hijacked.

export type EditorShortcutActions = {
  onCut: () => void
  onCopy: () => void
  onPaste: () => void
  onDelete: () => void
  onUndo: () => void
  onRedo: () => void
}

/** True when the event targets an editable field (input/textarea/contenteditable). */
function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return (
    tag === "INPUT" ||
    tag === "TEXTAREA" ||
    tag === "SELECT" ||
    el.isContentEditable === true
  )
}

export function useEditorShortcuts(
  actions: EditorShortcutActions,
  enabled = true
): void {
  const ref = useRef(actions)
  useEffect(() => {
    ref.current = actions
  }, [actions])
  // Read through a ref so the once-bound listener sees the latest value without
  // re-binding — mirrors `actions`. Lets the parent freeze buffer-mutating
  // shortcuts (cut/paste/delete/undo/redo) while a repaint job is in flight.
  const enabledRef = useRef(enabled)
  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!enabledRef.current) return
      if (isEditableTarget(e.target)) return
      const mod = e.metaKey || e.ctrlKey
      const a = ref.current
      const key = e.key.toLowerCase()

      // Redo before undo: Ctrl/Cmd+Shift+Z is a superset match of the Z key.
      if (mod && key === "z" && e.shiftKey) a.onRedo()
      else if (mod && key === "y" && !e.shiftKey) a.onRedo()
      else if (mod && key === "z" && !e.shiftKey) a.onUndo()
      else if (mod && key === "x") a.onCut()
      else if (mod && key === "c") a.onCopy()
      else if (mod && key === "v") a.onPaste()
      else if (!mod && (e.key === "Delete" || e.key === "Backspace")) a.onDelete()
      else return

      e.preventDefault()
    }
    window.addEventListener("keydown", onKeyDown)
    return () => window.removeEventListener("keydown", onKeyDown)
  }, [])
}
