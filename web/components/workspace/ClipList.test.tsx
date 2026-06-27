import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ClipList } from "@/components/workspace/ClipList"
import type { Clip } from "@/lib/workspace-clips"

function clip(id: string): Clip {
  return {
    id,
    workspace_id: "w1",
    title: id,
    format: "wav",
    duration: 60,
    bpm: null,
    key: null,
    style_tags: [],
    lyrics: null,
    vocal_language: null,
    model: null,
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: null,
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
  }
}

describe("ClipList", () => {
  it("shows a skeleton while loading", () => {
    render(<ClipList clips={[]} loading />)
    expect(screen.getByTestId("clip-list-skeleton")).toBeInTheDocument()
  })

  it("shows the empty message when there are no clips", () => {
    render(<ClipList clips={[]} loading={false} emptyMessage="Nothing here." />)
    expect(screen.getByText("Nothing here.")).toBeInTheDocument()
  })

  it("renders a card per clip", () => {
    render(<ClipList clips={[clip("a"), clip("b")]} loading={false} />)
    expect(screen.getAllByTestId("clip-card")).toHaveLength(2)
  })
})
