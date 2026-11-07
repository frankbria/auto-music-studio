"use client"

import Link from "next/link"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { MasteringStatusBadge } from "@/components/mastering/mastering-status"
import { useMasteringHistory } from "@/hooks/use-mastering-history"
import { relativeTime } from "@/lib/notifications"
import {
  masteredHref,
  masteringDisplayStatus,
  profileLabel,
  serviceLabel,
  type MasteringHistoryItem,
} from "@/lib/mastering"
import { cn } from "@/lib/utils"

/**
 * Mastering history (US-21.3, #738): the selected song's mastering jobs with
 * their status, linking an approved master to its song page. Hidden until a
 * song is selected.
 */
export function MasteringHistory({
  clipId,
  refreshKey,
}: {
  clipId: string | undefined
  refreshKey?: string
}) {
  const history = useMasteringHistory(clipId, refreshKey)
  if (!clipId) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle>Mastering history</CardTitle>
        <CardDescription>
          This song&apos;s mastering jobs and approved master.
        </CardDescription>
      </CardHeader>
      <CardContent>{renderBody()}</CardContent>
    </Card>
  )

  function renderBody() {
    if (history.state.status === "loading") {
      return (
        <p role="status" className="text-sm text-muted-foreground">
          Loading mastering history…
        </p>
      )
    }
    if (history.state.status === "error") {
      return (
        <div className="flex flex-col items-start gap-3">
          <p className="text-sm text-destructive">
            Couldn&apos;t load mastering history.
          </p>
          <Button variant="outline" size="sm" onClick={history.reload}>
            Try again
          </Button>
        </div>
      )
    }
    if (history.state.jobs.length === 0) {
      return (
        <p className="text-sm text-muted-foreground">
          No mastering jobs for this song yet.
        </p>
      )
    }
    return (
      <ul className="flex flex-col gap-2" aria-label="Mastering history">
        {history.state.jobs.map((job) => (
          <li key={job.job_id}>
            <HistoryRow job={job} />
          </li>
        ))}
      </ul>
    )
  }
}

/** A single history row. Approved rows link to the master; the rest are static. */
function HistoryRow({ job }: { job: MasteringHistoryItem }) {
  const href = masteredHref(job)
  const body = (
    <>
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium">
          {profileLabel(job.profile)} · {serviceLabel(job.service)}
        </span>
        {job.created_at && (
          <span className="text-xs text-muted-foreground">
            {relativeTime(job.created_at)}
          </span>
        )}
      </span>
      <MasteringStatusBadge status={masteringDisplayStatus(job)} />
    </>
  )

  const className = cn(
    "flex items-center justify-between gap-3 rounded-md border border-input p-3",
    href && "transition-colors hover:bg-muted/50"
  )

  return href ? (
    <Link href={href} className={className}>
      {body}
    </Link>
  ) : (
    <div className={className}>{body}</div>
  )
}
