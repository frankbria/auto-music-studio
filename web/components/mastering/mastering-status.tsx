"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import type { IconSvgElement } from "@hugeicons/react"
import {
  Alert01Icon,
  ArrowTurnBackwardIcon,
  CheckmarkCircle01Icon,
  Clock01Icon,
  Loading03Icon,
  PlayCircle02Icon,
} from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

/** The five spec status states (US-21.3), each rendered visually distinct (AC2).
 *  Backend jobs only report queued/processing/completed/failed; the frontend
 *  splits completed into preview_ready vs approved (see masteringDisplayStatus). */
export type MasteringDisplayStatus =
  | "queued"
  | "processing"
  | "preview_ready"
  | "approved"
  | "failed"

/** The active-flow panel also shows a pre-queue "submitting" beat. */
export type MasteringStatusPhase = MasteringDisplayStatus | "submitting"

type StatusMeta = { icon: IconSvgElement; label: string; tone: string; spin?: boolean }

// One icon + label + accent per state — the single source of the status vocabulary,
// shared by the active-flow panel and the history rows so a state looks the same
// everywhere (AC2). queued/processing keep motion cues; the terminal states get a
// solid icon and a distinct color.
const STATUS_META: Record<MasteringStatusPhase, StatusMeta> = {
  submitting: { icon: Loading03Icon, label: "Submitting mastering job…", tone: "text-muted-foreground", spin: true },
  queued: { icon: Clock01Icon, label: "Queued", tone: "text-amber-500" },
  processing: { icon: Loading03Icon, label: "Processing", tone: "text-sky-500", spin: true },
  preview_ready: { icon: PlayCircle02Icon, label: "Preview ready", tone: "text-violet-500" },
  approved: { icon: CheckmarkCircle01Icon, label: "Approved", tone: "text-emerald-500" },
  failed: { icon: Alert01Icon, label: "Failed", tone: "text-destructive" },
}

/** Compact inline status pill (icon + label) for lists like the mastering history. */
export function MasteringStatusBadge({ status }: { status: MasteringDisplayStatus }) {
  const meta = STATUS_META[status]
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", meta.tone)}>
      <HugeiconsIcon
        icon={meta.icon}
        size={14}
        className={meta.spin ? "animate-spin" : undefined}
      />
      {meta.label}
    </span>
  )
}

/**
 * Mastering job status panel (US-21.2, extended for US-21.3). Renders the current
 * job state distinctly: a spinner/label while it runs (submitting → queued →
 * processing), a distinct badge once a master is ready or approved
 * (preview_ready / approved), and an error message with Retry when it fails.
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

  const meta = STATUS_META[status]
  return (
    <p role="status" className={cn("flex items-center gap-2 text-sm", meta.tone)}>
      <HugeiconsIcon
        icon={meta.icon}
        size={18}
        className={meta.spin ? "animate-spin" : undefined}
      />
      {meta.label}
    </p>
  )
}
