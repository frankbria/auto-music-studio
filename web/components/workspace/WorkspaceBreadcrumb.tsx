"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowRight01Icon, Home01Icon } from "@hugeicons/core-free-icons"

import type { Workspace } from "@/lib/workspace-clips"

/**
 * "Workspaces > {name}" breadcrumb. The root segment is a button that fires
 * `onNavigate` (e.g. back to a workspace picker); the current workspace name is
 * the trailing, non-interactive segment.
 */
export function WorkspaceBreadcrumb({
  workspace,
  onNavigate,
}: {
  workspace: Workspace | null
  onNavigate?: () => void
}) {
  return (
    <nav aria-label="Workspace breadcrumb" className="flex items-center gap-1 text-sm">
      <button
        type="button"
        onClick={onNavigate}
        className="flex items-center gap-1 rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none"
      >
        <HugeiconsIcon icon={Home01Icon} size={14} />
        Workspaces
      </button>
      <HugeiconsIcon
        icon={ArrowRight01Icon}
        size={14}
        className="text-muted-foreground"
      />
      <span className="truncate font-medium text-foreground">
        {workspace?.name ?? "—"}
      </span>
    </nav>
  )
}
