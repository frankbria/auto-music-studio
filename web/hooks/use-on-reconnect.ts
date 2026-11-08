"use client"

import { useEffect, useLayoutEffect, useRef } from "react"

/**
 * Run `callback` when the browser comes back online (#339), so a read that failed while offline retries without the
 * user doing anything. The latest callback runs, so it sees the loader's current error state.
 */
export function useOnReconnect(callback: () => void): void {
  const latest = useRef(callback)
  // Layout, not passive: an "online" event between commit and passive effects would otherwise run a stale callback
  // that still sees the previous render's state, and the row that just failed would never retry.
  useLayoutEffect(() => {
    latest.current = callback
  })
  useEffect(() => {
    const reconnected = () => latest.current()
    window.addEventListener("online", reconnected)
    return () => window.removeEventListener("online", reconnected)
  }, [])
}
