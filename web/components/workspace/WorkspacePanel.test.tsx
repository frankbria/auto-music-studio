import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { WorkspacePanel } from "@/components/workspace/WorkspacePanel"
import type { Clip, Workspace } from "@/lib/workspace-clips"

let clipsResult: { data: unknown; loading: boolean; fetching: boolean; error: boolean }
let wsResult: { defaultWorkspace: Workspace | null; loading: boolean }
let likedIds: string[]

vi.mock("@/hooks/use-clips", () => ({ useClips: () => clipsResult }))
vi.mock("@/hooks/use-workspaces", () => ({ useWorkspaces: () => wsResult }))
vi.mock("@/contexts/player-context", () => ({
  usePlayer: () => ({ state: { likedIds } }),
}))

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
    generation_mode: "generate",
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

const workspace: Workspace = {
  id: "w1",
  name: "My Beats",
  clip_count: 3,
  is_default: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: null,
}

beforeEach(() => {
  likedIds = []
  wsResult = { defaultWorkspace: workspace, loading: false }
  clipsResult = {
    data: {
      clips: [
        clip("public-one", { is_public: true }),
        clip("private-two", { is_public: false }),
        clip("uploaded-three", { generation_mode: "upload" }),
      ],
      total: 3,
      page: 1,
      per_page: 20,
      total_pages: 1,
    },
    loading: false,
    fetching: false,
    error: false,
  }
})

afterEach(() => vi.clearAllMocks())

describe("WorkspacePanel", () => {
  it("renders the workspace breadcrumb and one card per clip", () => {
    render(<WorkspacePanel />)
    expect(screen.getByText("My Beats")).toBeInTheDocument()
    expect(screen.getAllByTestId("clip-card")).toHaveLength(3)
  })

  it("narrows the list with the client-side Public filter", async () => {
    render(<WorkspacePanel />)
    await userEvent.click(screen.getByRole("button", { name: /filters/i }))
    await userEvent.click(screen.getByLabelText("Public"))
    expect(screen.getAllByTestId("clip-card")).toHaveLength(1)
    expect(screen.getByText("public-one")).toBeInTheDocument()
  })

  it("narrows to liked clips using the player's likedIds", async () => {
    likedIds = ["uploaded-three"]
    render(<WorkspacePanel />)
    await userEvent.click(screen.getByRole("button", { name: /filters/i }))
    await userEvent.click(screen.getByLabelText("Liked"))
    expect(screen.getAllByTestId("clip-card")).toHaveLength(1)
    expect(screen.getByText("uploaded-three")).toBeInTheDocument()
  })

  it("shows a filtered empty message when nothing matches", async () => {
    render(<WorkspacePanel />)
    await userEvent.click(screen.getByRole("button", { name: /filters/i }))
    await userEvent.click(screen.getByLabelText("Liked")) // no liked ids
    expect(
      screen.getByText("No clips on this page match your filters.")
    ).toBeInTheDocument()
  })

  it("renders the pagination indicator", () => {
    render(<WorkspacePanel />)
    expect(within(screen.getByTestId("workspace-panel")).getByText("Page 1 of 1")).toBeInTheDocument()
  })
})
