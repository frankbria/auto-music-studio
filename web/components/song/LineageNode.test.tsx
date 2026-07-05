import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { LineageNode } from "@/components/song/LineageNode"
import type { LabeledNode } from "@/lib/lineage"

function node(overrides: Partial<LabeledNode> = {}): LabeledNode {
  return {
    id: "p1",
    title: "Parent Song",
    generation_mode: "remix",
    parent_clip_ids: [],
    depth: 1,
    created_at: "2026-01-01T00:00:00Z",
    label: "Remixed from",
    ...overrides,
  }
}

describe("LineageNode", () => {
  it("shows the relationship label and title, linking to the clip's song page", () => {
    render(<LineageNode node={node()} />)
    expect(screen.getByText("Remixed from")).toBeInTheDocument()
    expect(screen.getByText("Parent Song")).toBeInTheDocument()
    expect(screen.getByRole("link")).toHaveAttribute("href", "/song/p1")
  })

  it("falls back to 'Untitled clip' and keeps the full title in a tooltip", () => {
    render(<LineageNode node={node({ id: "p2", title: null })} />)
    expect(screen.getByText("Untitled clip")).toBeInTheDocument()
    expect(screen.getByRole("link")).toHaveAttribute("href", "/song/p2")
  })
})
