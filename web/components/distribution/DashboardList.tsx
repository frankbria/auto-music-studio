"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Alert01Icon, RefreshIcon } from "@hugeicons/core-free-icons"

import { Button } from "@/components/ui/button"
import { ReleaseCard } from "@/components/distribution/ReleaseCard"
import { useReleasesPoll } from "@/hooks/use-releases-poll"
import { relativeTime } from "@/lib/notifications"

/**
 * Distribution status dashboard (US-21.6, spec §42.5): lists every release with
 * per-channel status badges, external links, and rejection reasons, refreshed by
 * a visibility-gated poll so status changes from the platforms surface without a
 * page reload. Loading/empty/error states mirror the rest of the app (muted text
 * and a role="alert"; no Skeleton/Alert primitives exist in web/).
 */
export function DashboardList() {
  const { releases, loading, error, lastUpdated, refresh } = useReleasesPoll()

  if (loading) {
    return (
      <p role="status" className="text-sm text-muted-foreground">
        Loading releases…
      </p>
    )
  }

  // Full error state only before any data has loaded. Once we have releases, a
  // transient poll failure must NOT wipe the visible list — show an inline stale
  // banner over the last-good data instead (a background blip shouldn't blank the
  // whole dashboard for 30s until the next poll).
  if (error && !releases) {
    return (
      <div role="alert" className="flex flex-col items-start gap-3">
        <p className="flex items-center gap-2 text-sm text-destructive">
          <HugeiconsIcon icon={Alert01Icon} size={18} />
          {error}
        </p>
        <Button variant="outline" size="sm" onClick={refresh}>
          <HugeiconsIcon icon={RefreshIcon} size={16} />
          Retry
        </Button>
      </div>
    )
  }

  if (!releases || releases.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No releases yet. Prepare one from the Review tab to get started.
      </p>
    )
  }

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-600"
        >
          <HugeiconsIcon icon={Alert01Icon} size={14} />
          Couldn’t refresh — showing the last known statuses.
        </div>
      )}
      <div className="flex items-center justify-between">
        {lastUpdated && (
          <p className="text-xs text-muted-foreground" suppressHydrationWarning>
            Updated {relativeTime(new Date(lastUpdated).toISOString())}
          </p>
        )}
        <Button variant="ghost" size="sm" onClick={refresh}>
          <HugeiconsIcon icon={RefreshIcon} size={16} />
          Refresh
        </Button>
      </div>
      {releases.map((release) => (
        <ReleaseCard key={release.id} release={release} />
      ))}
    </div>
  )
}
