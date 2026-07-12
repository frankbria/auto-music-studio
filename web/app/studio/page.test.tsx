import { render, screen, waitFor } from "@testing-library/react"
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

import StudioPage from "@/app/studio/page"
import { AuthContext } from "@/contexts/auth-context"

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
    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
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
    const ruler = () =>
      document.querySelector('[aria-hidden="true"]') as HTMLElement
    const initialWidth = ruler().style.width
    await user.click(screen.getByRole("button", { name: "Zoom in" }))
    expect(ruler().style.width).not.toBe(initialWidth)
  })
})

describe("StudioPage ?song= preload", () => {
  it("adds a track and renders the preloaded clip on the timeline", async () => {
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonRes({
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
        })
      )
    )
    renderPage()
    await waitFor(() => expect(screen.getByText("My Song")).toBeInTheDocument())
  })

  it("fetches the clip named by the song query param", async () => {
    searchParamsRef.current = new URLSearchParams("song=clip-1")
    const fetchMock = vi.fn().mockResolvedValue(
      jsonRes({
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
      })
    )
    vi.stubGlobal("fetch", fetchMock)
    renderPage()
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/clips/clip-1",
        expect.objectContaining({ headers: { authorization: "Bearer tok" } })
      )
    )
  })

  it("does not fetch a clip without a song param", () => {
    const fetchMock = vi.fn()
    vi.stubGlobal("fetch", fetchMock)
    renderPage()
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
