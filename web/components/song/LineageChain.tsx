import { HugeiconsIcon } from "@hugeicons/react"
import { ArrowRight01Icon, MoreHorizontalIcon } from "@hugeicons/core-free-icons"

import { LineageNode } from "@/components/song/LineageNode"
import type { LineageColumn } from "@/lib/lineage"

// Horizontal ancestry chain for the song-detail lineage panel (US-17.7). Renders
// columns oldest → newest (left → right) with arrows pointing toward the current
// song; a mashup's multiple parents stack vertically inside one column. When the
// backend truncated the tree (`truncated`), a "⋯ earlier" marker leads the chain
// to show ancestors continue beyond what's displayed. Pure/presentational — data
// fetching lives in LineageSection.

export function LineageChain({
  columns,
  truncated,
}: {
  columns: LineageColumn[]
  truncated?: boolean
}) {
  return (
    <div
      className="flex items-stretch gap-2 overflow-x-auto pb-1"
      data-testid="lineage-chain"
    >
      {truncated && (
        <>
          <span
            className="flex w-24 shrink-0 flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border p-3 text-center text-xs text-muted-foreground"
            data-testid="lineage-truncated"
          >
            <HugeiconsIcon icon={MoreHorizontalIcon} size={16} />
            earlier ancestors
          </span>
          <Arrow />
        </>
      )}
      {columns.map((col, i) => (
        <div key={col.depth} className="flex items-stretch gap-2">
          <div className="flex flex-col justify-center gap-2">
            {col.nodes.map((node) => (
              <LineageNode key={node.id} node={node} />
            ))}
          </div>
          {i < columns.length - 1 && <Arrow />}
        </div>
      ))}
    </div>
  )
}

/** Connector arrow pointing toward the newer clip (rightward). */
function Arrow() {
  return (
    <span className="flex shrink-0 items-center text-muted-foreground" aria-hidden>
      <HugeiconsIcon icon={ArrowRight01Icon} size={18} />
    </span>
  )
}
