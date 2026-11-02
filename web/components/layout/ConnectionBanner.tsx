"use client"

import { useEffect, useSyncExternalStore } from "react"
import { useRouter } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

// A non-blocking notice while the browser is offline (#339). The page stays usable underneath, and coming back
// online refreshes the server-rendered data, so nothing waits on a manual reload.

function subscribe(onChange: () => void): () => void {
  window.addEventListener("online", onChange)
  window.addEventListener("offline", onChange)
  return () => {
    window.removeEventListener("online", onChange)
    window.removeEventListener("offline", onChange)
  }
}

export function ConnectionBanner() {
  const online = useSyncExternalStore(
    subscribe,
    () => navigator.onLine,
    () => true
  )
  const router = useRouter()

  useEffect(() => {
    const reconnect = () => router.refresh()
    window.addEventListener("online", reconnect)
    return () => window.removeEventListener("online", reconnect)
  }, [router])

  if (online) return null
  return (
    <div
      role="status"
      aria-live="polite"
      data-slot="connection-banner"
      className="fixed inset-x-0 top-0 z-50 flex items-center justify-center gap-2 bg-foreground px-4 py-2 text-sm text-background"
    >
      <HugeiconsIcon icon={Loading03Icon} size={16} className="animate-spin" />
      Connection lost — retrying when you&apos;re back online…
    </div>
  )
}
