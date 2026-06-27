import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ClipCard } from "@/components/workspace/ClipCard"
import type { Clip } from "@/lib/workspace-clips"

function clip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "c1",
    workspace_id: "w1",
    title: "Midnight",
    format: "wav",
    duration: 95,
    bpm: 120,
    key: "C",
    style_tags: ["lofi", "chill"],
    lyrics: null,
    vocal_language: null,
    model: null,
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: "generate",
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

describe("ClipCard", () => {
  it("renders title, duration, and style tags", () => {
    render(<ClipCard clip={clip()} />)
    expect(screen.getByText("Midnight")).toBeInTheDocument()
    expect(screen.getByText("1:35")).toBeInTheDocument()
    expect(screen.getByText("lofi, chill")).toBeInTheDocument()
  })

  it("falls back to a placeholder title for untitled clips", () => {
    render(<ClipCard clip={clip({ title: null })} />)
    expect(screen.getByText("Untitled clip")).toBeInTheDocument()
  })
})
