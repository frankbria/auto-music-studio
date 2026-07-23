"use client"

import Link from "next/link"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { MasteringStatusBadge } from "@/components/mastering/mastering-status"
import { relativeTime } from "@/lib/notifications"
import {
  masteredHref,
  masteringDisplayStatus,
  masteringHistory,
  type MasteringHistoryEntry,
} from "@/lib/mastering-history"
import { MASTERING_PROFILES, MASTERING_SERVICES } from "@/lib/mastering"
import { cn } from "@/lib/utils"

function profileLabel(value: string) {
  return MASTERING_PROFILES.find((p) => p.value === value)?.label ?? value
}
function serviceLabel(value: string) {
  return MASTERING_SERVICES.find((s) => s.value === value)?.label ?? value
}

/**
 * Mastering history (US-21.3): past mastering jobs for the current user with their
 * status, and a link to the approved master where one exists (AC4). Reads the local
 * history seam (lib/mastering-history) until a backend listing endpoint exists.
 */
export function MasteringHistory({
  entries = masteringHistory,
}: {
  entries?: MasteringHistoryEntry[]
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Mastering history</CardTitle>
        <CardDescription>Your recent mastering jobs and approved masters.</CardDescription>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">No mastering jobs yet.</p>
        ) : (
          <ul className="flex flex-col gap-2" aria-label="Mastering history">
            {entries.map((entry) => (
              <li key={entry.id}>
                <HistoryRow entry={entry} />
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}

/** A single history row. Approved rows link to the master; the rest are static. */
function HistoryRow({ entry }: { entry: MasteringHistoryEntry }) {
  const href = masteredHref(entry)
  const body = (
    <>
      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm font-medium">{entry.songTitle}</span>
        <span className="text-xs text-muted-foreground">
          {profileLabel(entry.profile)} · {serviceLabel(entry.service)} ·{" "}
          {relativeTime(entry.createdAt)}
        </span>
      </span>
      <MasteringStatusBadge status={masteringDisplayStatus(entry)} />
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
