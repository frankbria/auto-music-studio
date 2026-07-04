import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useSongActions } from "@/hooks/use-song-actions"
import type { Clip } from "@/lib/workspace-clips"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

const authValue = {
  user: { id: "u1", email: "a@b.co" },
  accessToken: "tok",
  isAuthenticated: true,
  isLoading: false,
  login: vi.fn(),
  completeLogin: vi.fn(),
  logout: vi.fn(),
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
  )
}

function clip(overrides: Partial<Clip> = {}): Clip {
  return {
    id: "c1",
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
    generation_mode: null,
    parent_clip_ids: [],
    is_public: false,
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  }
}

function setup(c: Clip = clip()) {
  return renderHook(() => useSongActions(c), { wrapper })
}

afterEach(() => {
  vi.clearAllMocks()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("useSongActions", () => {
  it("routes navigation actions to the editor and studio pages", () => {
    const { result } = setup()
    act(() => result.current.handleAction("open-editor"))
    expect(push).toHaveBeenCalledWith("/editor/c1")

    act(() => result.current.handleAction("open-studio"))
    expect(push).toHaveBeenCalledWith("/studio?song=c1")
  })

  it("opens and closes the workflow modal for modal actions", () => {
    const { result } = setup()
    act(() => result.current.handleAction("remaster"))
    expect(result.current.activeModal).toBe("remaster")

    act(() => result.current.closeModal())
    expect(result.current.activeModal).toBeNull()
  })

  it("toggles publish state optimistically", () => {
    const { result } = setup()
    expect(result.current.isPublic).toBe(false)

    act(() => result.current.handleAction("publish-toggle"))
    expect(result.current.isPublic).toBe(true)

    act(() => result.current.handleAction("publish-toggle"))
    expect(result.current.isPublic).toBe(false)
  })

  it("asks for confirmation before deleting, then deletes and leaves", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)

    const { result } = setup()
    act(() => result.current.handleAction("delete"))
    expect(result.current.confirmingDelete).toBe(true)
    expect(fetchMock).not.toHaveBeenCalled()

    await act(() => result.current.confirmDelete())

    const [url, opts] = fetchMock.mock.calls[0]
    expect(url).toBe("/api/clips/c1")
    expect(opts.method).toBe("DELETE")
    expect(
      (opts.headers as Record<string, string>).authorization
    ).toBe("Bearer tok")
    expect(push).toHaveBeenCalledWith("/")
  })

  it("surfaces a delete failure and stays on the page", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 500 }))
    )

    const { result } = setup()
    act(() => result.current.handleAction("delete"))
    await act(() => result.current.confirmDelete())

    expect(push).not.toHaveBeenCalled()
    expect(result.current.actionError).toMatch(/delete/i)
    expect(result.current.deleting).toBe(false)
    // The dialog stays open so the user can retry or cancel.
    expect(result.current.confirmingDelete).toBe(true)

    act(() => result.current.cancelDelete())
    expect(result.current.confirmingDelete).toBe(false)
  })

  it("downloads audio in the requested format", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(new Uint8Array([1]), { status: 200 }))
    vi.stubGlobal("fetch", fetchMock)
    URL.createObjectURL = vi.fn().mockReturnValue("blob:x")
    URL.revokeObjectURL = vi.fn()
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {})

    const { result } = setup()
    act(() => result.current.handleAction("download-flac"))

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/clips/c1/audio?format=flac",
        expect.anything()
      )
    )
    expect(result.current.actionError).toBeNull()
  })

  it("surfaces a failed download", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 404 }))
    )

    const { result } = setup()
    act(() => result.current.handleAction("download-mp3"))

    await waitFor(() => expect(result.current.actionError).toMatch(/download/i))

    act(() => result.current.clearActionError())
    expect(result.current.actionError).toBeNull()
  })
})
