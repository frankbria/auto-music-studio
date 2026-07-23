"use client"

import { useEffect, useState } from "react"

/**
 * Debounce a rapidly-changing value (e.g. search keystrokes) so downstream
 * effects — like a server clip query — fire only after the value settles.
 * Extracted from WorkspacePanel (US-16.5) so the release SongSelector (US-21.1)
 * can reuse the exact same debounce behaviour.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(t)
  }, [value, delayMs])
  return debounced
}
