"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import type { IconSvgElement } from "@hugeicons/react"
import {
  Cancel01Icon,
  Clock01Icon,
  Edit02Icon,
  Globe02Icon,
  Tick02Icon,
  Upload04Icon,
} from "@hugeicons/core-free-icons"

import { channelLabel, type DistributionStatus } from "@/lib/releases"
import { cn } from "@/lib/utils"

type StatusMeta = { icon: IconSvgElement; label: string; tone: string }

// One icon + label + accent per distribution status — the single source of the
// dashboard's status vocabulary (mirrors mastering-status' STATUS_META). Neutral
// tone for the pre-submission states, semantic colour for the outcomes: sky for
// ready, violet for submitted, amber (waiting) for in_review, green for live,
// destructive for rejected.
const STATUS_META: Record<DistributionStatus, StatusMeta> = {
  draft: { icon: Edit02Icon, label: "Draft", tone: "text-muted-foreground" },
  ready: { icon: Tick02Icon, label: "Ready", tone: "text-sky-500" },
  submitted: { icon: Upload04Icon, label: "Submitted", tone: "text-violet-500" },
  in_review: { icon: Clock01Icon, label: "In Review", tone: "text-amber-500" },
  live: { icon: Globe02Icon, label: "Live", tone: "text-emerald-500" },
  rejected: { icon: Cancel01Icon, label: "Rejected", tone: "text-destructive" },
}

/** Compact status pill (icon + label). When `channel` is given it prefixes the
 *  channel name ("SoundCloud · Live") so per-channel rows read unambiguously.
 *  A plain span (not role="status"): these are persistent labels, and a
 *  dashboard of them must not become a dozen aria-live regions that re-announce
 *  on every poll (mirrors MasteringStatusBadge). */
export function StatusBadge({
  status,
  channel,
}: {
  status: DistributionStatus
  channel?: string
}) {
  const meta = STATUS_META[status]
  const label = channel ? `${channelLabel(channel)} · ${meta.label}` : meta.label
  return (
    <span className={cn("inline-flex items-center gap-1.5 text-xs font-medium", meta.tone)}>
      <HugeiconsIcon icon={meta.icon} size={14} />
      {label}
    </span>
  )
}
