import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"

import { ClipCard, type ClipCardProps } from "@/components/workspace/ClipCard"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"
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

/** Surfaces the global player's current track so play wiring is observable. */
function PlayerProbe() {
  const { state } = usePlayer()
  return (
    <>
      <div data-testid="current-track">{state.current?.id ?? "none"}</div>
      <div data-testid="current-title">{state.current?.title ?? "none"}</div>
    </>
  )
}

function renderCard(props: Partial<ClipCardProps> = {}) {
  return render(
    <PlayerProvider>
      <ClipCard clip={clip()} {...props} />
      <PlayerProbe />
    </PlayerProvider>
  )
}

describe("ClipCard", () => {
  it("renders title, duration, and style tags", () => {
    renderCard()
    expect(screen.getByText("Midnight")).toBeInTheDocument()
    expect(screen.getByText("1:35")).toBeInTheDocument()
    expect(screen.getByText("lofi, chill")).toBeInTheDocument()
  })

  it("falls back to a placeholder title for untitled clips", () => {
    render(
      <PlayerProvider>
        <ClipCard clip={clip({ title: null })} />
      </PlayerProvider>
    )
    expect(screen.getByText("Untitled clip")).toBeInTheDocument()
  })

  it("renders version and metadata badges from model/generation_mode", () => {
    render(
      <PlayerProvider>
        <ClipCard
          clip={clip({ model: "ace-step-v1", generation_mode: "extend" })}
        />
      </PlayerProvider>
    )
    expect(screen.getByText("XL")).toBeInTheDocument()
    expect(screen.getByText("Extend")).toBeInTheDocument()
  })

  it("sends the clip to the global player when Play is clicked", async () => {
    renderCard()
    expect(screen.getByTestId("current-track")).toHaveTextContent("none")
    await userEvent.click(screen.getByRole("button", { name: /play/i }))
    expect(screen.getByTestId("current-track")).toHaveTextContent("c1")
  })

  it("sends the optimistic title to the player after a rename", async () => {
    const onTitleChange = vi.fn()
    renderCard({ onTitleChange })
    await userEvent.click(screen.getByRole("button", { name: /edit title/i }))
    const input = screen.getByRole("textbox", { name: /title/i })
    await userEvent.clear(input)
    await userEvent.type(input, "New Name{Enter}")
    await userEvent.click(screen.getByRole("button", { name: /play/i }))
    expect(screen.getByTestId("current-title")).toHaveTextContent("New Name")
  })

  it("saves an inline title edit on Enter", async () => {
    const onTitleChange = vi.fn()
    renderCard({ onTitleChange })
    await userEvent.click(screen.getByRole("button", { name: /edit title/i }))
    const input = screen.getByRole("textbox", { name: /title/i })
    await userEvent.clear(input)
    await userEvent.type(input, "New Name{Enter}")
    expect(onTitleChange).toHaveBeenCalledWith("c1", "New Name")
    expect(screen.getByText("New Name")).toBeInTheDocument()
  })

  it("reverts an inline title edit on Escape", async () => {
    const onTitleChange = vi.fn()
    renderCard({ onTitleChange })
    await userEvent.click(screen.getByRole("button", { name: /edit title/i }))
    const input = screen.getByRole("textbox", { name: /title/i })
    await userEvent.clear(input)
    await userEvent.type(input, "Throwaway{Escape}")
    expect(onTitleChange).not.toHaveBeenCalled()
    expect(screen.getByText("Midnight")).toBeInTheDocument()
  })

  it("toggles like via the player store", async () => {
    renderCard()
    const like = screen.getByRole("button", { name: "Like" })
    expect(like).toHaveAttribute("aria-pressed", "false")
    await userEvent.click(like)
    expect(screen.getByRole("button", { name: "Unlike" })).toHaveAttribute(
      "aria-pressed",
      "true"
    )
  })

  it("fires dislike and share callbacks", async () => {
    const onDislike = vi.fn()
    const onShare = vi.fn()
    renderCard({ onDislike, onShare })
    await userEvent.click(screen.getByRole("button", { name: /dislike/i }))
    await userEvent.click(screen.getByRole("button", { name: /share/i }))
    expect(onDislike).toHaveBeenCalledWith("c1")
    expect(onShare).toHaveBeenCalledWith("c1")
  })

  it("toggles publish and reports the next visibility", async () => {
    const onPublishToggle = vi.fn()
    renderCard({ onPublishToggle })
    const publish = screen.getByRole("button", { name: /publish|make public/i })
    expect(publish).toHaveAttribute("aria-pressed", "false")
    await userEvent.click(publish)
    expect(onPublishToggle).toHaveBeenCalledWith("c1", true)
    expect(
      screen.getByRole("button", { name: /publish|make public|public/i })
    ).toHaveAttribute("aria-pressed", "true")
  })

  it("shows Get Full Song only for clips under 60s", async () => {
    const onGetFullSong = vi.fn()
    const { unmount } = render(
      <PlayerProvider>
        <ClipCard clip={clip({ duration: 30 })} onGetFullSong={onGetFullSong} />
      </PlayerProvider>
    )
    await userEvent.click(screen.getByRole("button", { name: /get full song/i }))
    expect(onGetFullSong).toHaveBeenCalledWith("c1")
    unmount()

    render(
      <PlayerProvider>
        <ClipCard clip={clip({ duration: 120 })} onGetFullSong={onGetFullSong} />
      </PlayerProvider>
    )
    expect(
      screen.queryByRole("button", { name: /get full song/i })
    ).not.toBeInTheDocument()
  })

  it("renders all spec 9.2 actions in the more-options menu", async () => {
    renderCard()
    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    const menu = screen.getByRole("menu")
    for (const label of [
      "Open in Studio",
      "Open in Editor",
      "Cover",
      "Extend",
      "Mashup",
      "Sample from Song",
      "Use as Inspiration",
      "Send to Mastering",
      "Export to DAW",
      "Create Music Video",
      "Delete",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
    // Remix/Edit and Download are submenus.
    expect(screen.getByText("Remix / Edit")).toBeInTheDocument()
    expect(screen.getByText("Download")).toBeInTheDocument()
    expect(menu).toBeInTheDocument()
  })

  it("does not duplicate generation actions in the more-options menu", async () => {
    renderCard()
    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    // Each §9.2 item appears exactly once (no submenu re-listing the flat items).
    expect(screen.getAllByText("Cover")).toHaveLength(1)
    expect(screen.getAllByText("Open in Studio")).toHaveLength(1)
    expect(screen.getAllByText("Sample from Song")).toHaveLength(1)
  })

  it("dispatches remix-edit from the more-options menu", async () => {
    const onMenuAction = vi.fn()
    renderCard({ onMenuAction })
    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    await userEvent.click(screen.getByRole("menuitem", { name: "Remix / Edit" }))
    expect(onMenuAction).toHaveBeenCalledWith("remix-edit", "c1")
  })

  it("dispatches a menu action from the Remix/Edit primary CTA", async () => {
    const onMenuAction = vi.fn()
    renderCard({ onMenuAction })
    await userEvent.click(
      screen.getByRole("button", { name: /remix or edit/i })
    )
    await userEvent.click(screen.getByRole("menuitem", { name: "Cover" }))
    expect(onMenuAction).toHaveBeenCalledWith("cover", "c1")
  })

  it("dispatches a download action with its format", async () => {
    const onMenuAction = vi.fn()
    renderCard({ onMenuAction })
    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    await userEvent.click(screen.getByRole("menuitem", { name: "Download" }))
    await userEvent.click(screen.getByRole("menuitem", { name: "WAV" }))
    expect(onMenuAction).toHaveBeenCalledWith("download-wav", "c1")
  })
})
