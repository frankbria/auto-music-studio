"use client"

import { useEffect, useRef } from "react"

/**
 * Run `callback` when the browser comes back online (#339), so a read that failed while offline retries without the
 * user doing anything. The latest callback runs, so it sees the loader's current error state.
 */
export function useOnReconnect(callback: () => void): void {
  const latest = useRef(callback)
  useEffect(() => {
    latest.current = callback
  })
  useEffect(() => {
    const reconnected = () => latest.current()
    window.addEventListener("online", reconnected)
    return () => window.removeEventListener("online", reconnected)
  }, [])
}
