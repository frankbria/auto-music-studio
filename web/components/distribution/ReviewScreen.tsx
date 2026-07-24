"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { Alert01Icon, MusicNote01Icon } from "@hugeicons/core-free-icons"

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { TargetSelector } from "@/components/distribution/TargetSelector"
import { formatTime } from "@/lib/clips"
import {
  loadDraft,
  prefillFromClip,
  REQUIRED_FIELDS,
  validateMetadata,
  type ReleaseMetadata,
} from "@/lib/release-draft"
import type { Clip } from "@/lib/workspace-clips"

/** Effective release metadata = clip prefill with any saved draft layered on top
 *  (same merge TargetSelector uses, so the review matches what will be submitted). */
function effectiveMetadata(clip: Clip): ReleaseMetadata {
  return { ...prefillFromClip(clip), ...loadDraft(clip.id) }
}

function coverArtLabel(m: ReleaseMetadata): string {
  switch (m.coverArt.kind) {
    case "uploaded":
      return `Uploaded (${m.coverArt.name})`
    case "existing":
      return "Using the song's artwork"
    case "none":
      return "None — add cover art before submitting"
  }
}

/** A label/value row; renders a muted "—" when the value is empty. */
function Row({ label, value }: { label: string; value: string | null | undefined }) {
  const shown = value && String(value).trim() ? value : "—"
  return (
    <div className="flex justify-between gap-4 py-1 text-sm">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium">{shown}</dd>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-sm font-semibold">{title}</h3>
      <dl className="divide-y divide-border">{children}</dl>
    </div>
  )
}

/**
 * Release review / summary screen (US-21.6, spec §42.4 step 7). Presents the
 * complete package — metadata, identifiers, audio details, cover art, and any
 * validation warnings — for a final check, then hands off submission to the
 * per-target workflows (TargetSelector) below. A missing-song state mirrors the
 * rest of the Distribute tab.
 */
export function ReviewScreen({ clip }: { clip: Clip | null }) {
  if (!clip) {
    return (
      <p className="text-sm text-muted-foreground">
        Select a song to review its release package.
      </p>
    )
  }

  const m = effectiveMetadata(clip)
  const errors = validateMetadata(m)
  // Blocking warnings: any required field still missing, plus no cover art.
  const warnings = [
    ...REQUIRED_FIELDS.filter(({ key }) => errors[key]).map(({ label }) => `${label} is required.`),
    ...(m.coverArt.kind === "none" ? ["Cover art is required for most stores."] : []),
    ...(errors.isrc ? [errors.isrc] : []),
    ...(errors.upc ? [errors.upc] : []),
  ]

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Review your release</CardTitle>
          <CardDescription>
            Check everything below before submitting. This is your last chance to
            catch issues before the release goes out.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-6">
          {warnings.length > 0 && (
            <div role="alert" className="flex flex-col gap-1 rounded-md border border-destructive/40 bg-destructive/5 p-3">
              <p className="flex items-center gap-2 text-sm font-medium text-destructive">
                <HugeiconsIcon icon={Alert01Icon} size={16} />
                {warnings.length} item{warnings.length > 1 ? "s" : ""} to fix
              </p>
              <ul className="ml-6 list-disc text-sm text-destructive">
                {warnings.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-center gap-4">
            <span className="flex size-20 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
              <HugeiconsIcon icon={MusicNote01Icon} size={28} />
            </span>
            <div className="min-w-0">
              <p className="truncate text-lg font-semibold">{m.title || "Untitled"}</p>
              <p className="truncate text-sm text-muted-foreground">{m.artist || "Unknown artist"}</p>
              <p className="text-xs text-muted-foreground">{coverArtLabel(m)}</p>
            </div>
          </div>

          <div className="grid gap-6 md:grid-cols-2">
            <Section title="Metadata">
              <Row label="Title" value={m.title} />
              <Row label="Artist" value={m.artist} />
              <Row label="Genre" value={m.genre} />
              <Row label="Album" value={m.album} />
              <Row label="Release date" value={m.releaseDate} />
              <Row label="Language" value={m.language} />
              <Row label="Explicit" value={m.explicit ? "Yes" : "No"} />
            </Section>

            <Section title="Identifiers">
              <Row label="ISRC" value={m.isrc} />
              <Row label="UPC" value={m.upc} />
              <Row label="Copyright" value={m.copyright} />
            </Section>

            <Section title="Audio">
              <Row label="Format" value={clip.format?.toUpperCase()} />
              <Row label="Duration" value={clip.duration ? formatTime(clip.duration) : null} />
              <Row label="BPM" value={m.bpm != null ? String(m.bpm) : null} />
              <Row label="Key" value={m.key} />
            </Section>

            {m.description.trim() && (
              <Section title="Description">
                <p className="py-1 text-sm">{m.description}</p>
              </Section>
            )}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Submit</CardTitle>
          <CardDescription>
            Publish to a connected platform, or prepare a package for a guided
            store. Each target runs its own submission workflow.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <TargetSelector clip={clip} />
        </CardContent>
      </Card>
    </div>
  )
}
