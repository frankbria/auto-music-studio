"use client"

import { useCallback, useState } from "react"

/** Cap the per-field history so a long editing session can't grow unbounded. */
export const UNDO_HISTORY_MAX = 20

/**
 * A string field with single-step undo backed by a small history stack (US-16.2).
 * `setValue` pushes a new entry (skipping no-op repeats); `undo` pops back to the
 * previous value. Lyrics and styles each own an instance. History is capped at
 * {@link UNDO_HISTORY_MAX}; older entries are evicted, so undo reverts to the most
 * recent retained state rather than growing without bound.
 */
export function useUndoableField(initial = "") {
  const [history, setHistory] = useState<string[]>([initial])

  const setValue = useCallback((next: string) => {
    setHistory((h) => {
      if (next === h[h.length - 1]) return h
      const appended = [...h, next]
      return appended.length > UNDO_HISTORY_MAX
        ? appended.slice(appended.length - UNDO_HISTORY_MAX)
        : appended
    })
  }, [])

  const undo = useCallback(() => {
    setHistory((h) => (h.length > 1 ? h.slice(0, -1) : h))
  }, [])

  return {
    value: history[history.length - 1],
    setValue,
    undo,
    canUndo: history.length > 1,
  }
}
