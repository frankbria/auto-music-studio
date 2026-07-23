"use client"

import { cn } from "@/lib/utils"
import { profileLabel, serviceLabel, type PreviewItem } from "@/lib/mastering"

/** Format a loudness delta with a sign (e.g. "+6.0 dB"), or a dash when absent. */
function formatDelta(delta?: number | null) {
  if (delta === null || delta === undefined) return "—"
  const sign = delta > 0 ? "+" : ""
  return `${sign}${delta.toFixed(1)} dB`
}

/**
 * The list of mastered previews (US-21.2). Each is a selectable card showing its
 * profile, service, and loudness delta vs. the original; the active card is
 * highlighted and loads into the A/B player. Renders an empty state when the
 * completed job produced no candidates.
 */
export function PreviewList({
  previews,
  selectedId,
  onSelect,
}: {
  previews: PreviewItem[]
  selectedId: string | null
  onSelect: (previewId: string) => void
}) {
  if (previews.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No mastered previews are available for this job.
      </p>
    )
  }

  return (
    <ul className="flex flex-col gap-2" aria-label="Mastered previews">
      {previews.map((p) => {
        const selected = p.preview_id === selectedId
        return (
          <li key={p.preview_id}>
            <button
              type="button"
              onClick={() => onSelect(p.preview_id)}
              aria-pressed={selected}
              className={cn(
                "flex w-full items-center justify-between gap-3 rounded-md border p-3 text-left transition-colors",
                selected
                  ? "border-primary bg-primary/5"
                  : "border-input hover:bg-muted/50"
              )}
            >
              <span className="flex flex-col">
                <span className="text-sm font-medium">
                  {profileLabel(p.profile)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {serviceLabel(p.service)}
                </span>
              </span>
              <span className="text-sm tabular-nums text-muted-foreground">
                {formatDelta(p.loudness_delta)}
              </span>
            </button>
          </li>
        )
      })}
    </ul>
  )
}
