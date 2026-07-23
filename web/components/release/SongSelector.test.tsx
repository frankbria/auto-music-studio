import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SongSelector } from "@/components/release/SongSelector"
import type { Clip, Workspace } from "@/lib/workspace-clips"

let clipsResult: { data: unknown; loading: boolean; error: boolean }
let wsResult: { defaultWorkspace: Workspace | null; loading: boolean }

vi.mock("@/hooks/use-clips", () => ({ useClips: () => clipsResult }))
vi.mock("@/hooks/use-workspaces", () => ({ useWorkspaces: () => wsResult }))

const workspace: Workspace = {
  id: "w1",
  name: "My Workspace",
  clip_count: 2,
  is_default: true,
  created_at: "2026-01-01",
  updated_at: null,
}

function clip(id: string, overrides: Partial<Clip> = {}): Clip {
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
    created_at: "2026-01-01",
    ...overrides,
  }
}

function clipsPage(clips: Clip[]) {
  return { clips, total: clips.length, page: 1, per_page: 20, total_pages: 1 }
}

afterEach(() => {
  vi.clearAllMocks()
})

describe("SongSelector", () => {
  it("shows a loading state while workspaces/clips load", () => {
    wsResult = { defaultWorkspace: null, loading: true }
    clipsResult = { data: null, loading: true, error: false }
    render(<SongSelector onSelect={vi.fn()} />)
    expect(screen.getByRole("status")).toHaveTextContent(/loading clips/i)
  })

  it("renders clips and calls onSelect with the clicked clip's id", async () => {
    wsResult = { defaultWorkspace: workspace, loading: false }
    clipsResult = {
      data: clipsPage([
        clip("c1", { title: "First Mix", duration: 65, generation_mode: "mastered" }),
        clip("c2", { title: "Second Mix" }),
      ]),
      loading: false,
      error: false,
    }
    const onSelect = vi.fn()
    const user = userEvent.setup()
    render(<SongSelector onSelect={onSelect} />)

    expect(screen.getByText("First Mix")).toBeInTheDocument()
    expect(screen.getByText(/1:05/)).toBeInTheDocument()
    // generation_mode badge is derived from the shared label map.
    expect(screen.getByText("Mastered")).toBeInTheDocument()

    await user.click(screen.getByText("Second Mix"))
    expect(onSelect).toHaveBeenCalledWith("c2")
  })

  it("shows an empty state when the workspace has no clips", () => {
    wsResult = { defaultWorkspace: workspace, loading: false }
    clipsResult = { data: clipsPage([]), loading: false, error: false }
    render(<SongSelector onSelect={vi.fn()} />)
    expect(screen.getByText(/no clips yet/i)).toBeInTheDocument()
  })

  it("shows an error state when the clip fetch fails", () => {
    wsResult = { defaultWorkspace: workspace, loading: false }
    clipsResult = { data: null, loading: false, error: true }
    render(<SongSelector onSelect={vi.fn()} />)
    expect(screen.getByText(/couldn't load clips/i)).toBeInTheDocument()
  })

  it("renders a Cancel button only when onCancel is provided", async () => {
    wsResult = { defaultWorkspace: workspace, loading: false }
    clipsResult = { data: clipsPage([clip("c1")]), loading: false, error: false }
    const onCancel = vi.fn()
    const user = userEvent.setup()
    const { rerender } = render(<SongSelector onSelect={vi.fn()} />)
    expect(screen.queryByRole("button", { name: /cancel/i })).not.toBeInTheDocument()

    rerender(<SongSelector onSelect={vi.fn()} onCancel={onCancel} />)
    await user.click(screen.getByRole("button", { name: /cancel/i }))
    expect(onCancel).toHaveBeenCalled()
  })
})
