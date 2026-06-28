"use client"

import { versionLabel } from "@/lib/clip-labels"
import { formatTime } from "@/lib/clips"
import type { Clip } from "@/lib/workspace-clips"

// Song-detail metadata panel (US-17.1): the clip's display fields. Only fields
// the backend ClipResponse actually carries are shown; null values are skipped
// so the panel never renders an empty "—".
//
// ponytail: mastering & distribution status are intentionally absent — they are
// not on ClipResponse and there is no clip→job/release lookup endpoint yet.
// Add those rows when such an endpoint lands (US-21.x mastering/distribution).

function formatDate(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  })
}

export function SongMetadata({ clip }: { clip: Clip }) {
  const rows: { label: string; value: string }[] = []
  const model = versionLabel(clip.model)
  if (model) rows.push({ label: "Model", value: model })
  if (clip.bpm != null) rows.push({ label: "BPM", value: String(clip.bpm) })
  if (clip.key) rows.push({ label: "Key", value: clip.key })
  if (clip.duration != null)
    rows.push({ label: "Duration", value: formatTime(clip.duration) })
  rows.push({ label: "Created", value: formatDate(clip.created_at) })
  rows.push({ label: "Visibility", value: clip.is_public ? "Public" : "Private" })

  return (
    <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-3">
      {rows.map((row) => (
        <div key={row.label} className="flex flex-col">
          <dt className="text-xs text-muted-foreground">{row.label}</dt>
          <dd className="font-medium tabular-nums">{row.value}</dd>
        </div>
      ))}
    </dl>
  )
}
