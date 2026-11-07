import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { ReactNode } from "react"

import { ClipList } from "@/components/workspace/ClipList"
import { AuthContext } from "@/contexts/auth-context"
import { PlayerProvider } from "@/contexts/player-context"
import type { Clip } from "@/lib/workspace-clips"

// Cards render a wired context menu (US-17.5), which needs auth + player context.
const authValue = {
  user: { id: "u1", email: "a@b.co" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}
function AllProviders({ children }: { children: ReactNode }) {
  return (
    <AuthContext.Provider value={authValue}>
      <PlayerProvider>{children}</PlayerProvider>
    </AuthContext.Provider>
  )
}

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
    render(
      <AllProviders>
        <ClipList clips={[clip("a"), clip("b")]} loading={false} />
      </AllProviders>
    )
    expect(screen.getAllByTestId("clip-card")).toHaveLength(2)
  })

  it("saves a card's inline rename to the clip (#736)", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"))
    vi.stubGlobal("fetch", fetchMock)
    render(
      <AllProviders>
        <ClipList clips={[clip("a"), clip("b")]} loading={false} />
      </AllProviders>
    )
    await userEvent.click(screen.getByRole("button", { name: "Edit title: b" }))
    const input = screen.getByRole("textbox", { name: "Title" })
    await userEvent.clear(input)
    await userEvent.type(input, "Renamed{Enter}")

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/clips/b",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ title: "Renamed" }),
      })
    )
    expect(await screen.findByText("Renamed")).toBeInTheDocument()
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})
