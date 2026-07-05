import { describe, expect, it } from "vitest"

import {
  lineageColumns,
  relationshipLabel,
  type LineageNode,
} from "@/lib/lineage"

function node(overrides: Partial<LineageNode> & { id: string }): LineageNode {
  return {
    title: overrides.id,
    generation_mode: null,
    parent_clip_ids: [],
    depth: 0,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

describe("relationshipLabel", () => {
  it("maps every known generation mode to its relationship phrase", () => {
    expect(relationshipLabel("extend")).toBe("Extended from")
    expect(relationshipLabel("cover")).toBe("Cover of")
    expect(relationshipLabel("remix")).toBe("Remixed from")
    expect(relationshipLabel("mashup")).toBe("Mashup of")
    expect(relationshipLabel("repaint")).toBe("Repainted from")
    expect(relationshipLabel("add_vocal")).toBe("Vocals added to")
    expect(relationshipLabel("sample")).toBe("Sampled from")
  })

  it("falls back to a generic phrase for null/unknown modes", () => {
    expect(relationshipLabel(null)).toBe("Derived from")
    expect(relationshipLabel("wormhole")).toBe("Derived from")
  })
})

describe("lineageColumns", () => {
  it("returns no columns for an original clip (subject only)", () => {
    expect(lineageColumns([node({ id: "c", depth: 0 })])).toEqual([])
  })

  it("orders ancestors oldest-first and labels each by its child's mode", () => {
    // C (remix) -> B (extend) -> A (original)
    const cols = lineageColumns([
      node({ id: "C", depth: 0, generation_mode: "remix", parent_clip_ids: ["B"] }),
      node({ id: "B", depth: 1, generation_mode: "extend", parent_clip_ids: ["A"] }),
      node({ id: "A", depth: 2, generation_mode: null, parent_clip_ids: [] }),
    ])
    // Leftmost = oldest (depth 2), rightmost = immediate parent (depth 1).
    expect(cols.map((c) => c.depth)).toEqual([2, 1])
    expect(cols[0].nodes[0]).toMatchObject({ id: "A", label: "Extended from" })
    expect(cols[1].nodes[0]).toMatchObject({ id: "B", label: "Remixed from" })
  })

  it("stacks multiple parents of a mashup in one column", () => {
    const cols = lineageColumns([
      node({ id: "M", depth: 0, generation_mode: "mashup", parent_clip_ids: ["X", "Y"] }),
      node({ id: "X", depth: 1 }),
      node({ id: "Y", depth: 1 }),
    ])
    expect(cols).toHaveLength(1)
    expect(cols[0].nodes.map((n) => n.id)).toEqual(["X", "Y"])
    expect(cols[0].nodes.every((n) => n.label === "Mashup of")).toBe(true)
  })

  it("labels a diamond ancestor by its closest child", () => {
    // D is a parent of both the subject S (depth 0) and C (depth 1); the
    // shallowest child wins, so D is labeled by S's mode, not C's.
    const cols = lineageColumns([
      node({ id: "S", depth: 0, generation_mode: "cover", parent_clip_ids: ["C", "D"] }),
      node({ id: "C", depth: 1, generation_mode: "remix", parent_clip_ids: ["D"] }),
      node({ id: "D", depth: 1, generation_mode: null, parent_clip_ids: [] }),
    ])
    const d = cols.flatMap((c) => c.nodes).find((n) => n.id === "D")
    expect(d?.label).toBe("Cover of") // via subject S (depth 0 child), the closest
  })
})
