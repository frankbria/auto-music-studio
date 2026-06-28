import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { SongHeader, type SongHeaderProps } from "@/components/song/SongHeader"
import { PlayerProvider } from "@/contexts/player-context"
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
    model: "ace-step-v1",
    seed: null,
    inference_steps: null,
    parent_clip_ids: [],
    generation_mode: "remix",
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

function renderHeader(props: Partial<SongHeaderProps> = {}) {
  return render(
    <PlayerProvider>
      <SongHeader clip={clip()} {...props} />
    </PlayerProvider>
  )
}

describe("SongHeader", () => {
  it("renders title, artist placeholder, and style/mode badges", () => {
    renderHeader()
    expect(screen.getByRole("heading", { name: "Midnight" })).toBeInTheDocument()
    expect(screen.getByText("Unknown artist")).toBeInTheDocument()
    expect(screen.getByText("Remix")).toBeInTheDocument() // mode
    expect(screen.getByText("XL")).toBeInTheDocument() // version
    expect(screen.getByText("lofi")).toBeInTheDocument()
  })

  it("toggles like state via the player store", async () => {
    const user = userEvent.setup()
    renderHeader()
    const like = screen.getByRole("button", { name: "Like" })
    expect(like).toHaveAttribute("aria-pressed", "false")
    await user.click(like)
    expect(
      screen.getByRole("button", { name: "Unlike" })
    ).toHaveAttribute("aria-pressed", "true")
  })

  it("optimistically toggles publish and emits the callback", async () => {
    const user = userEvent.setup()
    const onPublishToggle = vi.fn()
    renderHeader({ onPublishToggle })
    await user.click(
      screen.getByRole("button", { name: "Publish (make public)" })
    )
    expect(onPublishToggle).toHaveBeenCalledWith("c1", true)
    expect(
      screen.getByRole("button", { name: "Unpublish (make private)" })
    ).toBeInTheDocument()
  })

  it("emits dislike and share callbacks", async () => {
    const user = userEvent.setup()
    const onDislike = vi.fn()
    const onShare = vi.fn()
    renderHeader({ onDislike, onShare })
    await user.click(screen.getByRole("button", { name: "Dislike" }))
    await user.click(screen.getByRole("button", { name: "Share" }))
    expect(onDislike).toHaveBeenCalledWith("c1")
    expect(onShare).toHaveBeenCalledWith("c1")
  })
})
