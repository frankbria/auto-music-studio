import { render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ReviewScreen } from "@/components/distribution/ReviewScreen"
import type { Clip } from "@/lib/workspace-clips"

// Stub the submit surface — it pulls in auth/SoundCloud wiring we don't exercise
// here; this test is about the review summary itself.
vi.mock("@/components/distribution/TargetSelector", () => ({
  TargetSelector: () => <div data-testid="target-selector" />,
}))

function makeClip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "clip-1",
    workspace_id: "ws-1",
    title: "Neon Skyline",
    format: "wav",
    duration: 185,
    bpm: 128,
    key: "A minor",
    style_tags: ["Synthwave"],
    lyrics: null,
    vocal_language: null,
    model: null,
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: null,
    is_public: false,
    created_at: new Date().toISOString(),
    ...overrides,
  }
}

afterEach(() => {
  localStorage.clear()
  vi.clearAllMocks()
})

describe("ReviewScreen", () => {
  it("prompts to pick a song when none is selected", () => {
    render(<ReviewScreen clip={null} />)
    expect(screen.getByText(/select a song to review/i)).toBeInTheDocument()
  })

  it("summarizes metadata and audio details from the clip", () => {
    render(<ReviewScreen clip={makeClip()} />)
    expect(screen.getAllByText("Neon Skyline").length).toBeGreaterThan(0)
    expect(screen.getByText("Synthwave")).toBeInTheDocument() // genre from style_tags
    expect(screen.getByText("WAV")).toBeInTheDocument() // format upper-cased
    expect(screen.getByText("128")).toBeInTheDocument() // bpm
    expect(screen.getByText("A minor")).toBeInTheDocument() // key
    expect(screen.getByText("3:05")).toBeInTheDocument() // 185s duration
  })

  it("warns about missing required fields and cover art before submission", () => {
    // Prefill leaves genre blank when the clip has no style tags.
    render(<ReviewScreen clip={makeClip({ style_tags: [] })} />)
    const alert = screen.getByRole("alert")
    expect(alert).toHaveTextContent(/Genre is required/i)
    expect(alert).toHaveTextContent(/Cover art is required/i)
  })

  it("renders the per-target submit surface", () => {
    render(<ReviewScreen clip={makeClip()} />)
    expect(screen.getByTestId("target-selector")).toBeInTheDocument()
  })
})
