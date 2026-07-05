// Types + pure transforms for the song-detail generation-lineage panel (US-17.7).
//
// The backend GET /api/v1/clips/{id}/lineage (US-10.6) returns the subject clip's
// full ancestry as a flat, breadth-first list of light summaries: node[0] is the
// subject at depth 0, depth 1 its immediate parents, depth 2 their parents, and so
// on. `lineageColumns` turns that flat list into left-to-right columns (oldest
// ancestor first) with a per-node relationship label, ready for the chain view.

/** A lineage node as returned by the backend (a clip summary + its depth). */
export type LineageNode = {
  id: string
  title: string | null
  generation_mode: string | null
  parent_clip_ids: string[]
  /** 0 is the subject clip; 1 its parents; 2 their parents; … */
  depth: number
  created_at: string
}

/** Response shape of GET /api/v1/clips/{id}/lineage (ClipLineageResponse). */
export type ClipLineageResponse = {
  clip_id: string
  depth_limit: number
  /** True when ancestors remain beyond the depth cap (tree was truncated). */
  depth_truncated: boolean
  nodes: LineageNode[]
}

/** A lineage node paired with the label describing how its child derives from it. */
export type LabeledNode = LineageNode & { label: string }

/** One depth level of the chain (a mashup puts >1 node in a column). */
export type LineageColumn = { depth: number; nodes: LabeledNode[] }

/**
 * generation_mode → the relationship a *child* has to this parent. The label sits
 * on the parent because that's what the AC asks for ("Remixed from", "Cover of").
 * A child made by `remix` means its parent is what it was "Remixed from".
 */
const RELATIONSHIP_LABELS: Record<string, string> = {
  extend: "Extended from",
  cover: "Cover of",
  remix: "Remixed from",
  mashup: "Mashup of",
  repaint: "Repainted from",
  add_vocal: "Vocals added to",
  sample: "Sampled from",
}

/** Human-readable relationship label for a child's generation_mode. */
export function relationshipLabel(mode: string | null): string {
  if (!mode) return "Derived from"
  return RELATIONSHIP_LABELS[mode] ?? "Derived from"
}

/**
 * Turn the flat lineage node list into ordered columns for the chain view.
 *
 * Columns run oldest → newest (highest depth on the left, the subject's immediate
 * parents on the right); the subject itself (depth 0) is dropped — it's the page
 * you're on. Each ancestor is labeled by *its closest child's* generation_mode,
 * so a `remix` subject labels its parent "Remixed from". Ancestors owned by other
 * users are absent from the backend list, so they simply don't render.
 *
 * ponytail: a diamond ancestor (shared via two paths) is labeled by whichever
 * child is closest to the subject (smallest depth wins). Good enough until
 * multi-path lineage needs per-edge labels.
 */
export function lineageColumns(nodes: LineageNode[]): LineageColumn[] {
  // parent id → the generation_mode of its closest child. Walk children shallow
  // first so the nearest-to-subject child wins when an ancestor has several.
  const childMode = new Map<string, string | null>()
  for (const node of [...nodes].sort((a, b) => a.depth - b.depth)) {
    for (const pid of node.parent_clip_ids) {
      if (!childMode.has(pid)) childMode.set(pid, node.generation_mode)
    }
  }

  const byDepth = new Map<number, LabeledNode[]>()
  for (const node of nodes) {
    if (node.depth < 1) continue // drop the subject
    const label = relationshipLabel(
      childMode.has(node.id) ? childMode.get(node.id)! : null
    )
    const col = byDepth.get(node.depth) ?? []
    col.push({ ...node, label })
    byDepth.set(node.depth, col)
  }

  return [...byDepth.keys()]
    .sort((a, b) => b - a) // oldest (deepest) column first / leftmost
    .map((depth) => ({ depth, nodes: byDepth.get(depth)! }))
}
