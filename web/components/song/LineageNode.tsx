import Link from "next/link"
import { HugeiconsIcon } from "@hugeicons/react"
import { MusicNote01Icon } from "@hugeicons/core-free-icons"

import type { LabeledNode } from "@/lib/lineage"

// A single ancestor in the generation-lineage chain (US-17.7): a clickable card
// with a relationship label ("Remixed from"), the clip title, and a link to that
// clip's song page. Lineage nodes are light summaries with no artwork field, and
// there's no authed same-origin artwork proxy yet, so the thumbnail is a music
// glyph placeholder — swap in a real cover once /api/clips/{id}/artwork exists.

export function LineageNode({ node }: { node: LabeledNode }) {
  const title = node.title ?? "Untitled clip"
  return (
    <Link
      href={`/song/${encodeURIComponent(node.id)}`}
      data-testid="lineage-node"
      className="flex w-40 shrink-0 flex-col gap-2 rounded-lg border border-border bg-card p-3 transition-colors hover:bg-accent focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none"
    >
      <span className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase">
        {node.label}
      </span>
      <span className="flex items-center gap-2">
        <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
          <HugeiconsIcon icon={MusicNote01Icon} size={16} />
        </span>
        <span className="truncate text-sm font-medium" title={title}>
          {title}
        </span>
      </span>
    </Link>
  )
}
