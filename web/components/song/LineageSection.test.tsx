import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { LineageSection } from "@/components/song/LineageSection"
import { makeClip } from "@/test/clip-factory"
import type { LineageNode } from "@/lib/lineage"

const useLineage = vi.fn()
vi.mock("@/hooks/use-lineage", () => ({
  useLineage: (id: string) => useLineage(id),
}))

type HookState = {
  nodes: LineageNode[]
  truncated: boolean
  loading: boolean
  error: boolean
}

function setHook(state: Partial<HookState>) {
  useLineage.mockReturnValue({
    nodes: [],
    truncated: false,
    loading: false,
    error: false,
    ...state,
  })
}

function node(id: string, depth: number, extra: Partial<LineageNode> = {}): LineageNode {
  return {
    id,
    title: id,
    generation_mode: null,
    parent_clip_ids: [],
    depth,
    created_at: "2026-01-01T00:00:00Z",
    ...extra,
  }
}

afterEach(() => {
  vi.clearAllMocks()
})

describe("LineageSection", () => {
  it("renders nothing and skips the fetch for an original clip (no parents)", () => {
    const { container } = render(
      <LineageSection clip={makeClip({ parent_clip_ids: [] })} />
    )
    expect(container).toBeEmptyDOMElement()
    expect(useLineage).not.toHaveBeenCalled()
  })

  it("shows a loading skeleton while the ancestry fetches", () => {
    setHook({ loading: true })
    render(<LineageSection clip={makeClip({ parent_clip_ids: ["p1"] })} />)
    expect(screen.getByTestId("lineage-loading")).toBeInTheDocument()
  })

  it("renders the chain when ancestors resolve", () => {
    setHook({
      nodes: [
        node("c1", 0, { generation_mode: "remix", parent_clip_ids: ["p1"] }),
        node("p1", 1),
      ],
    })
    render(<LineageSection clip={makeClip({ id: "c1", parent_clip_ids: ["p1"] })} />)
    expect(
      screen.getByRole("heading", { name: "Generation history" })
    ).toBeInTheDocument()
    expect(screen.getByTestId("lineage-node")).toHaveAttribute("href", "/song/p1")
    expect(screen.getByText("Remixed from")).toBeInTheDocument()
  })

  it("hides itself when no ancestors resolve (all filtered out / error)", () => {
    setHook({ nodes: [node("c1", 0, { parent_clip_ids: ["p1"] })], error: true })
    const { container } = render(
      <LineageSection clip={makeClip({ id: "c1", parent_clip_ids: ["p1"] })} />
    )
    expect(container).toBeEmptyDOMElement()
  })
})
