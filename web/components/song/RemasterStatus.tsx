"use client"

import { useRouter } from "next/navigation"
import { HugeiconsIcon } from "@hugeicons/react"
import { Loading03Icon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import type { ClipEditState } from "@/hooks/use-clip-edit"

// Inline status for the one-click Remaster action (US-17.3). Remaster has no
// modal, so its progress/success/error surface here on the song page: a spinner
// while it runs, a "View" link to the remastered clip on success, and a
// dismissible error otherwise.

export function RemasterStatus({
  state,
  onDismiss,
}: {
  state: ClipEditState
  onDismiss: () => void
}) {
  const router = useRouter()

  if (state.phase === "submitting" || state.phase === "polling") {
    return (
      <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
        <HugeiconsIcon icon={Loading03Icon} className="animate-spin" data-icon="inline-start" />
        Remastering…
      </p>
    )
  }

  if (state.phase === "success") {
    const newClipId = state.clipIds[0]
    return (
      <div role="status" className="flex items-center gap-3 text-sm">
        <span>Remaster ready.</span>
        {newClipId && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => router.push(`/song/${encodeURIComponent(newClipId)}`)}
          >
            View
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    )
  }

  if (state.phase === "error") {
    return (
      <div role="alert" className="flex items-center gap-3 text-sm text-destructive">
        <span>{state.message}</span>
        <Button size="sm" variant="ghost" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    )
  }

  return null
}
