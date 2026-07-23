import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SelectedSongSummary } from "@/components/release/SelectedSongSummary"
import type { Clip } from "@/lib/workspace-clips"

function clip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "c1",
    workspace_id: "w1",
    title: "My Mixdown",
    format: "wav",
    duration: 65,
    bpm: null,
    key: null,
    style_tags: [],
    lyrics: null,
    vocal_language: null,
    model: null,
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: "studio",
    is_public: false,
    created_at: "2026-01-01",
    ...overrides,
  }
}

describe("SelectedSongSummary", () => {
  it("shows the title, formatted duration, and status badges", () => {
    render(<SelectedSongSummary clip={clip()} onChangeSong={vi.fn()} />)
    expect(screen.getByText("My Mixdown")).toBeInTheDocument()
    expect(screen.getByText(/1:05/)).toBeInTheDocument()
    expect(screen.getByText(/not mastered/i)).toBeInTheDocument()
    expect(screen.getByText(/not distributed/i)).toBeInTheDocument()
  })

  it("shows a Mastered badge when the clip's generation_mode is mastered", () => {
    render(
      <SelectedSongSummary
        clip={clip({ generation_mode: "mastered" })}
        onChangeSong={vi.fn()}
      />
    )
    expect(screen.getByText("Mastered")).toBeInTheDocument()
    expect(screen.queryByText(/not mastered/i)).not.toBeInTheDocument()
  })

  it("falls back to 'Untitled' when the clip has no title", () => {
    render(
      <SelectedSongSummary clip={clip({ title: null })} onChangeSong={vi.fn()} />
    )
    expect(screen.getByText("Untitled")).toBeInTheDocument()
  })

  it("calls onChangeSong when Change Song is clicked", async () => {
    const onChangeSong = vi.fn()
    const user = userEvent.setup()
    render(<SelectedSongSummary clip={clip()} onChangeSong={onChangeSong} />)
    await user.click(screen.getByRole("button", { name: /change song/i }))
    expect(onChangeSong).toHaveBeenCalled()
  })
})
