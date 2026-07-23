import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { SongMetadata } from "@/components/song/SongMetadata"
import type { Clip } from "@/lib/workspace-clips"

function clip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "c1",
    workspace_id: "w1",
    title: "Song",
    format: "wav",
    duration: 95,
    bpm: 120,
    key: "C",
    style_tags: [],
    lyrics: null,
    vocal_language: null,
    model: "ace-step-v1",
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: "generate",
    is_public: true,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

describe("SongMetadata", () => {
  it("maps the model id to its version label", () => {
    render(<SongMetadata clip={clip()} />)
    expect(screen.getByText("Model")).toBeInTheDocument()
    expect(screen.getByText("XL")).toBeInTheDocument()
  })

  it("shows BPM, key, and duration", () => {
    render(<SongMetadata clip={clip()} />)
    expect(screen.getByText("120")).toBeInTheDocument()
    expect(screen.getByText("C")).toBeInTheDocument()
    expect(screen.getByText("1:35")).toBeInTheDocument()
  })

  it("reflects visibility from is_public", () => {
    render(<SongMetadata clip={clip({ is_public: true })} />)
    expect(screen.getByText("Public")).toBeInTheDocument()
  })

  it("shows the three-state visibility label, including Unlisted", () => {
    render(<SongMetadata clip={clip({ visibility: "unlisted", is_public: false })} />)
    expect(screen.getByText("Unlisted")).toBeInTheDocument()
  })

  it("omits null fields instead of rendering blanks", () => {
    render(<SongMetadata clip={clip({ bpm: null, key: null, model: null })} />)
    expect(screen.queryByText("BPM")).not.toBeInTheDocument()
    expect(screen.queryByText("Key")).not.toBeInTheDocument()
    expect(screen.queryByText("Model")).not.toBeInTheDocument()
    // Always-present fields remain.
    expect(screen.getByText("Created")).toBeInTheDocument()
  })
})
