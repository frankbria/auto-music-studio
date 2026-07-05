import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SongDetail } from "@/components/song/SongDetail"
import { PlayerProvider } from "@/contexts/player-context"
import type { Clip } from "@/lib/workspace-clips"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({
    accessToken: "tok",
    isLoading: false,
    isAuthenticated: true,
  }),
}))

const push = vi.fn()
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
  usePathname: () => "/song/c1",
}))

function clip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "c1",
    workspace_id: "w1",
    title: "Midnight Drive",
    format: "wav",
    duration: 95,
    bpm: 120,
    key: "C minor",
    style_tags: ["lofi", "chill"],
    lyrics: "[Verse 1]\nDriving through the night\n[Chorus]\nNeon lights",
    vocal_language: "en",
    model: "ace-step-v1",
    seed: 7,
    inference_steps: 30,
    parent_clip_ids: [],
    generation_mode: "generate",
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

/** Stub fetch so the clip, similar, profile, and delete endpoints respond. */
function stubFetch(opts: {
  clip?: Clip
  clipStatus?: number
  similar?: Clip[]
  tier?: string
  deleteStatus?: number
}) {
  const fetchMock = vi.fn((input: string, init?: RequestInit) => {
    const url = String(input)
    if (url.includes("/similar")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({ clips: opts.similar ?? [], total: 0, limit: 6 }),
          { status: 200 }
        )
      )
    }
    if (url.includes("/users/me")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({ subscription_tier: opts.tier ?? "free" }),
          { status: 200 }
        )
      )
    }
    if (init?.method === "DELETE") {
      return Promise.resolve(
        new Response(null, { status: opts.deleteStatus ?? 204 })
      )
    }
    const status = opts.clipStatus ?? 200
    return Promise.resolve(
      new Response(JSON.stringify(opts.clip ?? {}), { status })
    )
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

function renderDetail(clipId = "c1") {
  return render(
    <PlayerProvider>
      <SongDetail clipId={clipId} />
    </PlayerProvider>
  )
}

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("SongDetail", () => {
  it("loads and renders the song's data", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    expect(await screen.findByText("Midnight Drive")).toBeInTheDocument()
  })

  it("renders the metadata fields", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await screen.findByText("Midnight Drive")
    expect(screen.getByText("BPM")).toBeInTheDocument()
    expect(screen.getByText("120")).toBeInTheDocument()
    expect(screen.getByText("C minor")).toBeInTheDocument()
    // "1:35" (95s) shows in both the player time readout and the metadata.
    expect(screen.getAllByText("1:35").length).toBeGreaterThanOrEqual(1)
    expect(screen.getByText("Private")).toBeInTheDocument()
  })

  it("renders the waveform player with click-to-seek support", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await screen.findByText("Midnight Drive")
    expect(screen.getByRole("img", { name: "Waveform" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument()
  })

  it("renders lyrics with structure tags formatted", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await screen.findByText("Midnight Drive")
    expect(screen.getByText("[Verse 1]")).toBeInTheDocument()
    expect(screen.getByText("[Chorus]")).toBeInTheDocument()
    expect(screen.getByText("Driving through the night")).toBeInTheDocument()
  })

  it("exposes inline like/dislike/share/publish actions", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await screen.findByText("Midnight Drive")
    expect(screen.getByRole("button", { name: "Like" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Dislike" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Share" })).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Publish (make public)" })
    ).toBeInTheDocument()
  })

  it("shows related songs when the similar endpoint returns clips", async () => {
    stubFetch({
      clip: clip(),
      similar: [clip({ id: "c2", title: "Related One" })],
    })
    renderDetail()
    await screen.findByText("Midnight Drive")
    expect(await screen.findByText("Related One")).toBeInTheDocument()
  })

  it("does not show the previous song when the id changes mid-fetch", async () => {
    // First clip resolves; the second id's fetch never resolves, so the page
    // must fall back to loading rather than keep rendering the first song.
    const fetchMock = vi.fn((input: string) => {
      const url = String(input)
      if (url.includes("/similar")) {
        return Promise.resolve(
          new Response(JSON.stringify({ clips: [] }), { status: 200 })
        )
      }
      if (url.includes("/c1")) {
        return Promise.resolve(
          new Response(JSON.stringify(clip()), { status: 200 })
        )
      }
      return new Promise<Response>(() => {}) // c2 hangs
    })
    vi.stubGlobal("fetch", fetchMock)

    const { rerender } = render(
      <PlayerProvider>
        <SongDetail clipId="c1" />
      </PlayerProvider>
    )
    await screen.findByText("Midnight Drive")

    rerender(
      <PlayerProvider>
        <SongDetail clipId="c2" />
      </PlayerProvider>
    )
    await waitFor(() =>
      expect(screen.getByTestId("song-loading")).toBeInTheDocument()
    )
    expect(screen.queryByText("Midnight Drive")).not.toBeInTheDocument()
  })

  it("shows a not-found state for a 404", async () => {
    stubFetch({ clip: clip(), clipStatus: 404 })
    renderDetail()
    await waitFor(() =>
      expect(screen.getByTestId("song-not-found")).toBeInTheDocument()
    )
  })
})

describe("SongDetail full action menu (US-17.2)", () => {
  async function openActions() {
    await screen.findByText("Midnight Drive")
    await userEvent.click(
      screen.getByRole("button", { name: /song actions menu/i })
    )
  }

  it("renders every category group from the action menu", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await openActions()
    for (const category of ["Edit", "Create", "Audio", "Export", "Manage"]) {
      expect(screen.getByText(category)).toBeInTheDocument()
    }
  })

  it("opens the workflow modal for a modal action", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await openActions()
    await userEvent.click(screen.getByRole("menuitem", { name: /^crop$/i }))

    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent("Crop")
    expect(within(dialog).getByLabelText("Start")).toBeInTheDocument()
    expect(within(dialog).getByLabelText("End")).toBeInTheDocument()
  })

  it("navigates to the studio from the menu", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await openActions()
    await userEvent.click(
      screen.getByRole("menuitem", { name: /open in studio/i })
    )
    expect(push).toHaveBeenCalledWith("/studio?song=c1")
  })

  it("shows the placeholder modal for Open in Editor (pro user) until US-18", async () => {
    stubFetch({ clip: clip(), tier: "pro" })
    renderDetail()
    await openActions()
    await userEvent.click(
      screen.getByRole("menuitem", { name: /open in editor/i })
    )
    // No /editor route exists yet — navigating would 404.
    expect(push).not.toHaveBeenCalledWith("/editor/c1")
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      "Open in Editor"
    )
  })

  it("locks Pro-only actions for a free user", async () => {
    stubFetch({ clip: clip(), tier: "free" })
    renderDetail()
    await openActions()
    expect(
      screen.getByRole("menuitem", { name: /open in editor/i })
    ).toHaveAttribute("aria-disabled", "true")
  })

  it("shares publish state between the menu and the header button", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await openActions()
    await userEvent.click(screen.getByRole("menuitem", { name: /publish/i }))

    expect(
      screen.getByRole("button", { name: "Unpublish (make private)" })
    ).toBeInTheDocument()

    // And the other direction: the header button updates the menu label.
    await userEvent.click(
      screen.getByRole("button", { name: "Unpublish (make private)" })
    )
    await openActions()
    expect(screen.getByRole("menuitem", { name: /^publish$/i })).toBeInTheDocument()
  })

  it("closes the workflow modal with Escape", async () => {
    stubFetch({ clip: clip() })
    renderDetail()
    await openActions()
    await userEvent.click(screen.getByRole("menuitem", { name: /^cover$/i }))
    await screen.findByRole("dialog")

    await userEvent.keyboard("{Escape}")
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    )
  })

  it("cancels delete without calling the backend", async () => {
    const fetchMock = stubFetch({ clip: clip() })
    renderDetail()
    await openActions()
    await userEvent.click(screen.getByRole("menuitem", { name: /delete/i }))
    await screen.findByRole("dialog")

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }))
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
    )
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE")
    ).toHaveLength(0)
  })

  it("deletes the song after confirmation and navigates home", async () => {
    const fetchMock = stubFetch({ clip: clip() })
    renderDetail()
    await openActions()
    await userEvent.click(screen.getByRole("menuitem", { name: /delete/i }))

    // Nothing deleted until confirmed.
    const dialog = await screen.findByRole("dialog")
    expect(dialog).toHaveTextContent(/permanently deleted/i)
    expect(
      fetchMock.mock.calls.filter(([, init]) => init?.method === "DELETE")
    ).toHaveLength(0)

    await userEvent.click(screen.getByRole("button", { name: "Delete" }))

    await waitFor(() => expect(push).toHaveBeenCalledWith("/"))
    const deletes = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "DELETE"
    )
    expect(deletes).toHaveLength(1)
    expect(String(deletes[0][0])).toBe("/api/clips/c1")
  })

  it("hides Get Full Song for a clip too long to seed one", async () => {
    stubFetch({ clip: clip({ duration: 95 }) })
    renderDetail()
    await openActions()
    expect(
      screen.queryByRole("menuitem", { name: /get full song/i })
    ).not.toBeInTheDocument()
  })

  it("offers Get Full Song for a short clip and opens the wizard", async () => {
    stubFetch({ clip: clip({ duration: 30 }) })
    renderDetail()
    await openActions()
    await userEvent.click(
      screen.getByRole("menuitem", { name: /get full song/i })
    )
    expect(await screen.findByRole("dialog")).toHaveTextContent("Get Full Song")
  })

  it("keeps the confirmation open with an error when delete fails", async () => {
    stubFetch({ clip: clip(), deleteStatus: 500 })
    renderDetail()
    await openActions()
    await userEvent.click(screen.getByRole("menuitem", { name: /delete/i }))
    await screen.findByRole("dialog")
    await userEvent.click(screen.getByRole("button", { name: "Delete" }))

    expect(await screen.findByRole("alert")).toHaveTextContent(/delete/i)
    expect(screen.getByRole("dialog")).toBeInTheDocument()
    expect(push).not.toHaveBeenCalledWith("/")
  })
})
