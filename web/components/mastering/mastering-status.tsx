"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import {
  Alert01Icon,
  ArrowTurnBackwardIcon,
  Loading03Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"

/** The in-progress/terminal-failure phases the status panel renders. */
export type MasteringStatusPhase =
  | "submitting"
  | "queued"
  | "processing"
  | "failed"

const LABELS: Record<Exclude<MasteringStatusPhase, "failed">, string> = {
  submitting: "Submitting mastering job…",
  queued: "Queued — waiting for a mastering slot…",
  processing: "Mastering in progress…",
}

/**
 * Mastering job progress + failure display (US-21.2). Shows a spinner and a
 * phase label while the job runs (submitting → queued → processing), and an
 * error message with a Retry button when it fails. The completed state is owned
 * by the tab (it swaps in the preview UI), so this never renders "completed".
 */
export function MasteringStatus({
  status,
  error,
  onRetry,
}: {
  status: MasteringStatusPhase
  error?: string
  onRetry?: () => void
}) {
  if (status === "failed") {
    return (
      <div role="alert" className="flex flex-col items-start gap-3">
        <p className="flex items-center gap-2 text-sm text-destructive">
          <HugeiconsIcon icon={Alert01Icon} size={18} />
          {error || "Mastering failed. Please try again."}
        </p>
        {onRetry && (
          <Button variant="outline" size="sm" onClick={onRetry}>
            <HugeiconsIcon icon={ArrowTurnBackwardIcon} size={16} />
            Retry
          </Button>
        )}
      </div>
    )
  }

  return (
    <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground">
      <HugeiconsIcon icon={Loading03Icon} size={18} className="animate-spin" />
      {LABELS[status]}
    </p>
  )
}
