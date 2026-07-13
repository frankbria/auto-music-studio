import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

const { searchParamsRef } = vi.hoisted(() => ({
  searchParamsRef: { current: new URLSearchParams() },
}))

// This page uses useSearchParams, which the shared setup mock doesn't provide.
vi.mock("next/navigation", () => ({
  usePathname: () => "/studio",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => searchParamsRef.current,
}))

const { getClipAudioMock } = vi.hoisted(() => ({
  getClipAudioMock: vi.fn(() => new Promise(() => {})),
}))
vi.mock("@/lib/clip-audio-cache", () => ({
  getClipAudio: getClipAudioMock,
}))

import { act } from "react"
import StudioPage from "@/app/studio/page"
import { AuthContext } from "@/contexts/auth-context"
import { PlayerProvider } from "@/contexts/player-context"

// --- Minimal Web Audio + rAF stand-ins (jsdom has neither), mirroring
// hooks/use-studio-playback.test.tsx's stubs. ---

class FakeGainNode {
  connect = vi.fn()
  disconnect = vi.fn()
  gain = { value: 1 }
}

class FakeSourceNode {
  buffer: AudioBuffer | null = null
  connect = vi.fn()
  disconnect = vi.fn()
  start = vi.fn()
  stop = vi.fn()
}

function stubAudioContext() {
  const box: { instance: { currentTime: number } | null } = { instance: null }
  class FakeAudioContext {
    currentTime = 0
    destination = {}
    createGain = vi.fn(() => new FakeGainNode())
    createBufferSource = vi.fn(() => new FakeSourceNode())
    close = vi.fn().mockResolvedValue(undefined)
    constructor() {
      box.instance = this
    }
  }
  vi.stubGlobal("AudioContext", FakeAudioContext)
  return box
}

function stubRaf() {
  let nextId = 1
  const callbacks = new Map<number, FrameRequestCallback>()
  vi.stubGlobal(
    "requestAnimationFrame",
    vi.fn((cb: FrameRequestCallback) => {
      const id = nextId++
      callbacks.set(id, cb)
      return id
    })
  )
  vi.stubGlobal(
    "cancelAnimationFrame",
    vi.fn((id: number) => {
      callbacks.delete(id)
    })
  )
  return {
    /** Invoke every currently-scheduled rAF callback once, at time `t`. */
    tick(t: number) {
      const due = [...callbacks.entries()]
      callbacks.clear()
      for (const [, cb] of due) cb(t)
    },
  }
}

const authValue = {
  user: { id: "u1", email: "a@b.co" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}

function renderPage(overrides: Partial<typeof authValue> = {}) {
  const value = { ...authValue, ...overrides }
  function wrapper({ children }: { children: ReactNode }) {
    return (
      <AuthContext.Provider value={value}>
        <PlayerProvider>{children}</PlayerProvider>
      </AuthContext.Provider>
    )
  }
  return render(<StudioPage />, { wrapper })
}

function jsonRes(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status })
}

afterEach(() => {
  searchParamsRef.current = new URLSearchParams()
  vi.unstubAllGlobals()
  getClipAudioMock.mockClear()
})

describe("StudioPage auth gate", () => {
  it("renders nothing while auth is loading", () => {
    const { container } = renderPage({
      isLoading: true,
      isAuthenticated: false,
    })
    expect(container).toBeEmptyDOMElement()
  })

  it("renders nothing when unauthenticated", () => {
    const { container } = renderPage({ isAuthenticated: false })
    expect(container).toBeEmptyDOMElement()
  })
})

describe("StudioPage header", () => {
  it("renders the title and a display-mode toggle defaulting to Bars/Beats", () => {
    renderPage()
    expect(screen.getByRole("heading", { name: "Studio" })).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Bars/Beats" })
    ).toBeInTheDocument()
  })

  it("toggles the display mode label on click", async () => {
    const user = userEvent.setup()
    renderPage()
    await user.click(screen.getByRole("button", { name: "Bars/Beats" }))
    expect(screen.getByRole("button", { name: "mm:ss" })).toBeInTheDocument()
  })

  it("zooms in and out via the header buttons", async () => {
    const user = userEvent.setup()
    renderPage()
    const ruler = () => screen.getByRole("img", { name: "Timeline" })
    const initialWidth = ruler().style.width
    await user.click(screen.getByRole("button", { name: "Zoom in" }))
    expect(ruler().style.width).not.toBe(initialWidth)
  })

  it("renders the transport controls", () => {
    renderPage()
    expect(screen.getByRole("button", { name: "Play" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Return to start" })
    ).toBeInTheDocument()
  })
})

describe("StudioPage playhead", () => {
  it("renders a playhead that seeks when the ruler is clicked", () => {
    renderPage()
    const ruler = screen.getByRole("img", { name: "Timeline" })
    vi.spyOn(ruler, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })

    const playhead = screen.getByTestId("playhead")
    // Playhead x includes TRACK_STRIP_PX (160) so it lines up with the lanes'
    // timeline region, not the outer container's raw left edge.
    expect(playhead.style.left).toBe("160px")

    fireEvent.click(ruler, { clientX: 100 })
    // Default zoom is 100 px/sec (BASE_PX_PER_SEC): 100px -> 1s -> 160+100px.
    expect(playhead.style.left).toBe("260px")
  })

  it("does not stomp a ruler seek made mid-playback on the next rAF tick", async () => {
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    stubStudioFetch()
    const box = stubAudioContext()
    const raf = stubRaf()
    getClipAudioMock.mockResolvedValue({
      buffer: {} as AudioBuffer,
      peaks: new Float32Array(),
      duration: 100,
    })

    renderPage()
    await waitFor(() => expect(screen.getByText("My Song")).toBeInTheDocument())

    await act(async () => {
      await userEvent.click(screen.getByRole("button", { name: "Play" }))
      await Promise.resolve()
      await Promise.resolve()
    })

    const ruler = screen.getByRole("img", { name: "Timeline" })
    vi.spyOn(ruler, "getBoundingClientRect").mockReturnValue({
      left: 0,
      top: 0,
      right: 0,
      bottom: 0,
      width: 0,
      height: 0,
      x: 0,
      y: 0,
      toJSON: () => ({}),
    })
    const playhead = screen.getByTestId("playhead")

    // One frame elapses (1s of ctx time) before the user seeks.
    act(() => {
      box.instance!.currentTime = 1
      raf.tick(1000)
    })
    expect(playhead.style.left).toBe("260px") // 160 + 1s * 100px/sec

    // User seeks to 5s mid-playback. The seek reschedules through the same
    // decode-then-tick path as the initial play (Fix 3), so let it settle.
    await act(async () => {
      fireEvent.click(ruler, { clientX: 500 })
      await Promise.resolve()
      await Promise.resolve()
    })
    expect(playhead.style.left).toBe("660px") // 160 + 500

    // Another 0.2s of ctx time elapses and the next rAF frame fires. Without
    // rescheduling off the seek, the stale origin (ctxTime=0, playheadSec=0)
    // would compute 1.2s here instead — reverting the user's seek.
    await act(async () => {
      box.instance!.currentTime = 1.2
      raf.tick(1200)
    })
    expect(playhead.style.left).toBe("680px") // 160 + 5.2s * 100px/sec
  })

  it("aligns the ruler's origin with the lanes' timeline region via a shared spacer width", async () => {
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    stubStudioFetch()
    renderPage()
    await waitFor(() => expect(screen.getByText("My Song")).toBeInTheDocument())

    // The ruler's spacer and each lane's control strip must share the exact
    // same width (TRACK_STRIP_PX) — otherwise a tick at sec=0 and a clip at
    // startSec=0 land at different x positions in the shared outer container.
    const spacerWidth = screen.getByTestId("ruler-spacer").style.width
    const stripWidth = screen.getByTestId("track-strip").style.width
    expect(spacerWidth).toBe(stripWidth)
    expect(spacerWidth).not.toBe("")
  })
})

const SONG_CLIP_JSON = {
  id: "clip-1",
  workspace_id: "w1",
  title: "My Song",
  format: "mp3",
  duration: 30,
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

/** Routes each fetch by URL — WorkspacePanel (/api/workspaces, /api/clips?…)
 * and useClip (/api/clips/{id}) race concurrently, and a Response body can
 * only be read once, so a single shared mockResolvedValue instance breaks
 * whichever hook loses the race. */
function stubStudioFetch(clipJson: unknown = SONG_CLIP_JSON) {
  const fetchMock = vi.fn((url: string) => {
    if (url.startsWith("/api/clips/") && !url.includes("?")) {
      return Promise.resolve(jsonRes(clipJson))
    }
    return Promise.resolve(jsonRes({ workspaces: [] }))
  })
  vi.stubGlobal("fetch", fetchMock)
  return fetchMock
}

describe("StudioPage ?song= preload", () => {
  it("adds a track and renders the preloaded clip on the timeline", async () => {
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    stubStudioFetch()
    renderPage()
    await waitFor(() => expect(screen.getByText("My Song")).toBeInTheDocument())
  })

  it("fetches the clip named by the song query param", async () => {
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    const fetchMock = stubStudioFetch()
    renderPage()
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/clips/clip-1",
        expect.objectContaining({ headers: { authorization: "Bearer tok" } })
      )
    )
  })

  it("preloads a second song after a client-side nav to a new ?song=", async () => {
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    const clipsById: Record<string, unknown> = {
      "clip-1": SONG_CLIP_JSON,
      "clip-2": { ...SONG_CLIP_JSON, id: "clip-2", title: "Second Song" },
    }
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const match = /^\/api\/clips\/([^/?]+)$/.exec(url)
        if (match) return Promise.resolve(jsonRes(clipsById[match[1]]))
        return Promise.resolve(jsonRes({ workspaces: [] }))
      })
    )

    const { rerender } = renderPage()
    await waitFor(() => expect(screen.getByText("My Song")).toBeInTheDocument())

    // Client-side nav to a different song — same page instance stays mounted.
    searchParamsRef.current = new URLSearchParams("song=clip-2")
    rerender(<StudioPage />)

    await waitFor(() =>
      expect(screen.getByText("Second Song")).toBeInTheDocument()
    )
    // The first song's track is untouched — this is a second preload, not a
    // replacement.
    expect(screen.getByText("My Song")).toBeInTheDocument()
  })

  it("does not fetch a clip without a song param", () => {
    const fetchMock = stubStudioFetch()
    renderPage()
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringMatching(/^\/api\/clips\/[^/]+$/),
      expect.anything()
    )
  })

  it("does not re-add a track when navigating back to an already-preloaded song (A→B→A)", async () => {
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    const clipsById: Record<string, unknown> = {
      "clip-1": SONG_CLIP_JSON,
      "clip-2": { ...SONG_CLIP_JSON, id: "clip-2", title: "Second Song" },
    }
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const match = /^\/api\/clips\/([^/?]+)$/.exec(url)
        if (match) return Promise.resolve(jsonRes(clipsById[match[1]]))
        return Promise.resolve(jsonRes({ workspaces: [] }))
      })
    )

    const { rerender } = renderPage()
    await waitFor(() => expect(screen.getByText("My Song")).toBeInTheDocument())

    searchParamsRef.current = new URLSearchParams("song=clip-2")
    rerender(<StudioPage />)
    await waitFor(() =>
      expect(screen.getByText("Second Song")).toBeInTheDocument()
    )

    // Nav back to the first song — a *previous* boolean-only guard would only
    // ever block the immediately-preceding id, so this would re-add clip-1
    // as a duplicate track (three lanes instead of two).
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    rerender(<StudioPage />)
    await waitFor(() =>
      expect(screen.getAllByTestId("track-lane")).toHaveLength(2)
    )
    expect(screen.getAllByText("My Song")).toHaveLength(1)
  })
})

describe("StudioPage clip library aside", () => {
  it("embeds the workspace panel as a drag source for the timeline", () => {
    stubStudioFetch()
    renderPage()
    expect(screen.getByTestId("workspace-panel")).toBeInTheDocument()
  })
})
