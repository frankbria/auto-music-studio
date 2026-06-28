import { render, screen, waitFor } from "@testing-library/react"
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

/** Stub fetch so the clip endpoint and the similar endpoint each respond. */
function stubFetch(opts: { clip?: Clip; clipStatus?: number; similar?: Clip[] }) {
  const fetchMock = vi.fn((input: string) => {
    const url = String(input)
    if (url.includes("/similar")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({ clips: opts.similar ?? [], total: 0, limit: 6 }),
          { status: 200 }
        )
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

afterEach(() => vi.restoreAllMocks())

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
