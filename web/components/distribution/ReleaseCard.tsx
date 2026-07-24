"use client"

import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import { Alert01Icon, LinkSquare02Icon, MusicNote01Icon } from "@hugeicons/core-free-icons"

import { Card, CardContent } from "@/components/ui/card"
import { StatusBadge } from "@/components/distribution/StatusBadge"
import { channelLabel, externalLink, type ReleaseSummary } from "@/lib/releases"

/** Format an ISO date as a short, locale-stable label (UTC to avoid SSR drift). */
function formatDate(iso: string): string {
  const d = new Date(iso)
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" })
}

/**
 * One release row for the distribution dashboard (US-21.6). Shows the cover
 * (music-glyph placeholder — no artwork proxy in web/), title/artist, release
 * date, identifiers, a per-channel StatusBadge, a live external link, and the
 * rejection reason when a channel was rejected.
 */
export function ReleaseCard({ release }: { release: ReleaseSummary }) {
  return (
    <Card>
      <CardContent className="flex items-start gap-4 p-4">
        <span className="flex size-16 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
          <HugeiconsIcon icon={MusicNote01Icon} size={24} />
        </span>

        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <div className="flex flex-col gap-0.5">
            <Link
              href={`/song/${release.clipId}`}
              className="truncate text-base font-semibold hover:underline"
            >
              {release.title}
            </Link>
            <p className="truncate text-sm text-muted-foreground">
              {release.artist} · {release.genre} · {formatDate(release.releaseDate)}
            </p>
            {(release.isrc || release.upc) && (
              <p className="text-xs text-muted-foreground tabular-nums">
                {release.isrc && <span>ISRC {release.isrc}</span>}
                {release.isrc && release.upc && <span> · </span>}
                {release.upc && <span>UPC {release.upc}</span>}
              </p>
            )}
          </div>

          <ul className="flex flex-col gap-1.5">
            {release.channels.map((ch) => {
              const link = externalLink(ch)
              return (
                <li key={ch.channel} className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center gap-3">
                    <StatusBadge status={ch.status} channel={ch.channel} />
                    {link && (
                      <a
                        href={link}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-xs font-medium text-sky-500 hover:underline"
                      >
                        <HugeiconsIcon icon={LinkSquare02Icon} size={13} />
                        View on {channelLabel(ch.channel)}
                      </a>
                    )}
                  </div>
                  {ch.status === "rejected" && (
                    <p className="flex items-start gap-1 text-xs text-destructive">
                      <HugeiconsIcon icon={Alert01Icon} size={13} className="mt-0.5 shrink-0" />
                      {ch.rejectionReason || "Reason unavailable."}
                    </p>
                  )}
                </li>
              )
            })}
          </ul>
        </div>
      </CardContent>
    </Card>
  )
}
