"use client"

import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowDown01Icon } from "@hugeicons/core-free-icons"

import { Badge } from "@/components/ui/badge"
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { GuidedFlowModal } from "@/components/distribution/GuidedFlowModal"
import { SoundCloudCard } from "@/components/distribution/SoundCloudCard"
import {
  DISTRIBUTION_TARGETS,
  type DistributionTarget,
  type GuidedTarget,
} from "@/lib/distribution"
import { loadDraft, prefillFromClip, type ReleaseMetadata } from "@/lib/release-draft"
import type { Clip } from "@/lib/workspace-clips"

type Props = {
  /** The selected song; null shows a prompt and disables guided actions. */
  clip: Clip | null
}

/** Effective release metadata = clip prefill with any saved draft layered on top. */
function effectiveMetadata(clip: Clip): ReleaseMetadata {
  return { ...prefillFromClip(clip), ...loadDraft(clip.id) }
}

/** Requirements list, collapsed by default via the native <details> element. */
function Requirements({ items }: { items: string[] }) {
  return (
    <details className="group text-sm">
      <summary className="flex cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground">
        <HugeiconsIcon
          icon={ArrowDown01Icon}
          size={14}
          className="transition-transform group-open:rotate-180"
        />
        Requirements
      </summary>
      <ul className="mt-2 ml-1 flex list-disc flex-col gap-1 pl-4 text-xs text-muted-foreground">
        {items.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </details>
  )
}

function TargetCard({
  target,
  clip,
}: {
  target: DistributionTarget
  clip: Clip | null
}) {
  return (
    <Card className="flex flex-col">
      <CardHeader>
        <div className="flex items-center justify-between gap-2">
          <CardTitle>{target.label}</CardTitle>
          <Badge variant={target.kind === "auto" ? "default" : "secondary"}>
            {target.kind === "auto" ? "Automated" : "Guided"}
          </Badge>
        </div>
        <CardDescription>{target.blurb}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {target.kind === "auto" ? (
          <SoundCloudCard />
        ) : (
          <div className="flex flex-col items-start gap-3">
            {!clip && (
              <p className="text-sm text-muted-foreground">
                Select a song to prepare a package.
              </p>
            )}
            <GuidedFlowModal
              target={target.id as GuidedTarget}
              ready={!!clip}
              // Read the draft fresh on open so the package reflects the latest
              // saved edits (the form persists on change), not a mount snapshot.
              resolveMetadata={() => (clip ? effectiveMetadata(clip) : null)}
            />
          </div>
        )}
        <div className="mt-auto">
          <Requirements items={target.requirements} />
        </div>
      </CardContent>
    </Card>
  )
}

/** Distribution target selection grid (US-21.5): SoundCloud + guided LANDR/DistroKid. */
export function TargetSelector({ clip }: Props) {
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {DISTRIBUTION_TARGETS.map((target) => (
        <TargetCard key={target.id} target={target} clip={clip} />
      ))}
    </div>
  )
}
