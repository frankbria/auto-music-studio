import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { ClipCard, type ClipCardProps } from "@/components/workspace/ClipCard"
import { AuthContext } from "@/contexts/auth-context"
import { PlayerProvider, usePlayer } from "@/contexts/player-context"
import { parseClipDragData, readDragTrackType } from "@/lib/clip-drag"
import type { Clip } from "@/lib/workspace-clips"

// The ⋯ menu now dispatches through useSongActions (US-17.5): navigation uses the
// router, downloads call downloadClipAudio, delete hits the DELETE proxy. Capture
// the router push and stub the download so those effects are observable/inert.
const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

const downloadClipAudio = vi.fn<(...args: unknown[]) => Promise<boolean>>(() =>
  Promise.resolve(true)
)
vi.mock("@/lib/clips", async (importActual) => ({
  ...(await importActual<typeof import("@/lib/clips")>()),
  downloadClipAudio: (...args: unknown[]) => downloadClipAudio(...args),
}))

const authValue = {
  user: { id: "u1", email: "a@b.co" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}

/** Auth + player context every card needs now that the menu is wired. */
function AllProviders({ children }: { children: ReactNode }) {
  return (
    <AuthContext.Provider value={authValue}>
      <PlayerProvider>{children}</PlayerProvider>
    </AuthContext.Provider>
  )
}

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
    <AllProviders>
      <ClipCard clip={clip()} {...props} />
      <PlayerProbe />
    </AllProviders>
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
      <AllProviders>
        <ClipCard clip={clip({ title: null })} />
      </AllProviders>
    )
    expect(screen.getByText("Untitled clip")).toBeInTheDocument()
  })

  it("renders version and metadata badges from model/generation_mode", () => {
    render(
      <AllProviders>
        <ClipCard
          clip={clip({ model: "ace-step-v1", generation_mode: "extend" })}
        />
      </AllProviders>
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

  it("shows the current visibility as a badge", () => {
    renderCard()
    expect(screen.getByText("Private")).toBeInTheDocument()
  })

  it("changes visibility to public for a ready clip, persisting via the PATCH proxy", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ id: "c1", visibility: "public" }), {
          status: 200,
        })
      )
    vi.stubGlobal("fetch", fetchMock)
    const onVisibilityChange = vi.fn()
    renderCard({ onVisibilityChange })

    await userEvent.click(
      screen.getByRole("button", { name: "Visibility: Private" })
    )
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Public" }))

    expect(onVisibilityChange).toHaveBeenCalledWith("c1", "public")
    await waitFor(() =>
      expect(screen.getByText("Public")).toBeInTheDocument()
    )
    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/c1")
    expect(opts.method).toBe("PATCH")
    expect(JSON.parse(opts.body as string)).toEqual({
      visibility: "public",
    })
    vi.unstubAllGlobals()
  })

  it("changes visibility to unlisted without a guard, even on an incomplete clip", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(
        new Response(JSON.stringify({ id: "c1", visibility: "unlisted" }), {
          status: 200,
        })
      )
    )
    vi.stubGlobal("fetch", fetchMock)
    render(
      <AllProviders>
        <ClipCard clip={clip({ title: null, style_tags: [] })} />
      </AllProviders>
    )

    await userEvent.click(
      screen.getByRole("button", { name: "Visibility: Private" })
    )
    await userEvent.click(
      screen.getByRole("menuitemradio", { name: "Unlisted" })
    )

    await waitFor(() =>
      expect(screen.getByText("Unlisted")).toBeInTheDocument()
    )
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it("prompts instead of publishing an incomplete clip, without a PATCH", async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    render(
      <AllProviders>
        <ClipCard clip={clip({ style_tags: [] })} />
      </AllProviders>
    )
    await userEvent.click(
      screen.getByRole("button", { name: "Visibility: Private" })
    )
    await userEvent.click(screen.getByRole("menuitemradio", { name: "Public" }))

    expect(await screen.findByRole("dialog")).toHaveTextContent(
      /before publishing/i
    )
    expect(fetchMock).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it("persists dislike via the player store", async () => {
    renderCard()
    const dislike = screen.getByRole("button", { name: /dislike/i })
    expect(dislike).toHaveAttribute("aria-pressed", "false")
    await userEvent.click(dislike)
    expect(dislike).toHaveAttribute("aria-pressed", "true")
  })

  it("opens the share modal with a copyable link", async () => {
    renderCard()
    await userEvent.click(screen.getByRole("button", { name: /share/i }))
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent(/share/i)
    expect(screen.getByLabelText("Share link")).toBeInTheDocument()
  })

  it("shows Get Full Song only for clips under 60s", async () => {
    const onGetFullSong = vi.fn()
    const { unmount } = render(
      <AllProviders>
        <ClipCard clip={clip({ duration: 30 })} onGetFullSong={onGetFullSong} />
      </AllProviders>
    )
    await userEvent.click(
      screen.getByRole("button", { name: /get full song/i })
    )
    expect(onGetFullSong).toHaveBeenCalledWith("c1")
    unmount()

    render(
      <AllProviders>
        <ClipCard
          clip={clip({ duration: 120 })}
          onGetFullSong={onGetFullSong}
        />
      </AllProviders>
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
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Remix / Edit" })
    )
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

  // US-17.5: the ⋯ menu is now wired to real workflows, not just an observer.
  it("navigates to the studio for Open in Studio", async () => {
    renderCard()
    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Open in Studio" })
    )
    expect(push).toHaveBeenCalledWith("/studio?song=c1")
  })

  it("opens a workflow modal for an editing action", async () => {
    renderCard()
    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    await userEvent.click(
      screen.getByRole("menuitem", { name: "Use as Inspiration" })
    )
    // Placeholder modal until the workflow ships — proves modal dispatch is wired.
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      /Use as Inspiration/i
    )
  })

  it("downloads the clip's audio in the chosen format", async () => {
    renderCard()
    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    await userEvent.click(screen.getByRole("menuitem", { name: "Download" }))
    await userEvent.click(screen.getByRole("menuitem", { name: "MP3" }))
    expect(downloadClipAudio).toHaveBeenCalledWith(
      "c1",
      "mp3",
      "tok",
      "Midnight"
    )
  })

  it("confirms before deleting, then calls the proxy and drops the card", async () => {
    const fetchMock = vi.fn(() => Promise.resolve({ status: 204 } as Response))
    vi.stubGlobal("fetch", fetchMock)
    const onDeleted = vi.fn()
    renderCard({ onDeleted })

    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete" }))
    // A confirmation dialog gates the delete — nothing is called yet.
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      /Delete this song\?/i
    )
    expect(fetchMock).not.toHaveBeenCalled()

    await userEvent.click(screen.getByRole("button", { name: "Delete" }))
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/clips/c1",
        expect.objectContaining({ method: "DELETE" })
      )
    )
    expect(onDeleted).toHaveBeenCalledWith("c1")
    vi.unstubAllGlobals()
  })

  it("locks Pro-only items and flags Beta for free-tier users", async () => {
    renderCard({ isFreeTier: true })
    await userEvent.click(screen.getByRole("button", { name: /more options/i }))
    expect(screen.getByText("Beta")).toBeInTheDocument()
    // Open in Editor is Pro-gated: disabled so a click can never dispatch it.
    expect(
      screen.getByRole("menuitem", { name: /Open in Editor/i })
    ).toHaveAttribute("aria-disabled", "true")
  })

  it("is draggable, carrying an 'add' payload for the Studio timeline (US-19.1)", () => {
    renderCard({
      clip: clip({
        id: "c1",
        title: "Midnight",
        duration: 95,
        generation_mode: "sound",
        bpm: 90,
      }),
    })
    const card = screen.getByTestId("clip-card")
    expect(card).toHaveAttribute("draggable", "true")

    const store = new Map<string, string>()
    const dataTransfer = {
      setData: (type: string, value: string) => store.set(type, value),
      getData: (type: string) => store.get(type) ?? "",
      get types() {
        return [...store.keys()]
      },
    } as unknown as DataTransfer
    fireEvent.dragStart(card, { dataTransfer })

    expect(parseClipDragData(dataTransfer)).toEqual({
      kind: "add",
      clipId: "c1",
      title: "Midnight",
      duration: 95,
      generationMode: "sound",
      bpm: 90,
    })
    // Track type entry, readable during dragover for drop-target validation
    // (US-19.2): a "sound" clip belongs on Sound/Loop tracks.
    expect(readDragTrackType(dataTransfer)).toBe("loop")
  })
})
