"use client"

import { Button } from "@/components/ui/button"

/**
 * Failed-generation state (US-16.7): a meaningful message plus Retry (resubmit the
 * same request) and Dismiss (clear back to idle). Used by all three creation forms.
 */
export function GenerationError({
  message,
  onRetry,
  onDismiss,
}: {
  message: string
  onRetry: () => void
  onDismiss: () => void
}) {
  return (
    <div role="alert" className="flex flex-col gap-2 text-sm text-destructive">
      <p>{message}</p>
      <div className="flex gap-2">
        <Button type="button" size="sm" variant="outline" onClick={onRetry}>
          Retry
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={onDismiss}>
          Dismiss
        </Button>
      </div>
    </div>
  )
}
