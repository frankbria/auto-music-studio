import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { LineageChain } from "@/components/song/LineageChain"
import type { LineageColumn } from "@/lib/lineage"

function labeled(id: string, label: string) {
  return {
    id,
    title: id,
    generation_mode: null,
    parent_clip_ids: [],
    depth: 1,
    created_at: "2026-01-01T00:00:00Z",
    label,
  }
}

const chain: LineageColumn[] = [
  { depth: 2, nodes: [labeled("A", "Extended from")] },
  { depth: 1, nodes: [labeled("B", "Remixed from")] },
]

describe("LineageChain", () => {
  it("renders ancestors left-to-right in the given (oldest-first) column order", () => {
    render(<LineageChain columns={chain} />)
    const links = screen.getAllByTestId("lineage-node")
    expect(links.map((l) => l.getAttribute("href"))).toEqual([
      "/song/A",
      "/song/B",
    ])
  })

  it("stacks a mashup's multiple parents inside one column", () => {
    render(
      <LineageChain
        columns={[
          {
            depth: 1,
            nodes: [labeled("X", "Mashup of"), labeled("Y", "Mashup of")],
          },
        ]}
      />
    )
    expect(screen.getAllByTestId("lineage-node")).toHaveLength(2)
    expect(screen.getAllByText("Mashup of")).toHaveLength(2)
  })

  it("shows a truncation marker only when the tree was capped", () => {
    const { rerender } = render(<LineageChain columns={chain} />)
    expect(screen.queryByTestId("lineage-truncated")).not.toBeInTheDocument()

    rerender(<LineageChain columns={chain} truncated />)
    expect(screen.getByTestId("lineage-truncated")).toBeInTheDocument()
  })
})
