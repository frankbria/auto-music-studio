import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useSongActions } from "@/hooks/use-song-actions"
import type { Clip } from "@/lib/workspace-clips"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

const submitRemaster = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitRemaster: (...args: unknown[]) => submitRemaster(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
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

function setup(c: Clip = clip(), opts?: { onDeleted?: (id: string) => void }) {
  return renderHook(() => useSongActions(c, opts), { wrapper })
}

afterEach(() => {
  vi.clearAllMocks()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("useSongActions", () => {
  it("routes open-studio to the studio page", () => {
    const { result } = setup()
    act(() => result.current.handleAction("open-studio"))
    expect(push).toHaveBeenCalledWith("/studio?song=c1")
  })

  it("keeps open-editor on the placeholder modal until the editor ships", () => {
    const { result } = setup()
    act(() => result.current.handleAction("open-editor"))
    expect(push).not.toHaveBeenCalled()
    expect(result.current.activeModal).toBe("open-editor")
  })

  it("opens and closes the workflow modal for modal actions", () => {
    const { result } = setup()
    act(() => result.current.handleAction("cover"))
    expect(result.current.activeModal).toBe("cover")

    act(() => result.current.closeModal())
    expect(result.current.activeModal).toBeNull()
  })

  it("runs remaster inline (no modal) and drives its status to success", async () => {
    submitRemaster.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["remastered-1"] })
    const { result } = setup()

    await act(async () => {
      result.current.handleAction("remaster")
    })

    // No modal opens for the one-click action.
    expect(result.current.activeModal).toBeNull()
    await waitFor(() => expect(result.current.remasterState.phase).toBe("success"))
    expect(submitRemaster).toHaveBeenCalledWith("c1", {}, "tok")
  })

  it("ignores a repeat remaster while one is already running", async () => {
    submitRemaster.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    // Job never completes, so the first remaster stays in the polling phase.
    fetchJobStatus.mockResolvedValue({ kind: "pending" })
    const { result } = setup()

    await act(async () => {
      result.current.handleAction("remaster")
    })
    await waitFor(() => expect(result.current.remasterState.phase).toBe("polling"))

    // A second click while polling must not enqueue another job.
    act(() => result.current.handleAction("remaster"))
    expect(submitRemaster).toHaveBeenCalledTimes(1)

    act(() => result.current.dismissRemaster())
  })

  describe("publish toggle (US-17.6)", () => {
    const ready = () => clip({ title: "My Song", style_tags: ["lofi"] })

    it("persists an optimistic publish when the clip is ready", async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ id: "c1", is_public: true }), {
          status: 200,
        })
      )
      vi.stubGlobal("fetch", fetchMock)
      const { result } = setup(ready())
      expect(result.current.isPublic).toBe(false)

      await act(async () => {
        result.current.handleAction("publish-toggle")
      })
      await waitFor(() => expect(result.current.isPublic).toBe(true))

      const [url, opts] = fetchMock.mock.calls[0]
      expect(url).toBe("/api/clips/c1")
      expect(opts.method).toBe("PATCH")
      expect(JSON.parse(opts.body as string)).toEqual({ is_public: true })
      expect(result.current.publishGuard).toBeNull()
    })

    it("prompts (no request) when a style tag is missing", () => {
      const fetchMock = vi.fn()
      vi.stubGlobal("fetch", fetchMock)
      const { result } = setup(clip({ title: "My Song", style_tags: [] }))

      act(() => result.current.handleAction("publish-toggle"))
      expect(result.current.publishGuard).toEqual({
        missingTitle: false,
        missingStyleTags: true,
      })
      expect(result.current.isPublic).toBe(false)
      expect(fetchMock).not.toHaveBeenCalled()

      act(() => result.current.dismissPublishGuard())
      expect(result.current.publishGuard).toBeNull()
    })

    it("flags a missing title in the guard", () => {
      const { result } = setup(clip({ title: null, style_tags: ["lofi"] }))
      act(() => result.current.handleAction("publish-toggle"))
      expect(result.current.publishGuard).toEqual({
        missingTitle: true,
        missingStyleTags: false,
      })
    })

    it("rolls back and surfaces an error when the request fails", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response("{}", { status: 500 }))
      )
      const { result } = setup(ready())

      await act(async () => {
        result.current.handleAction("publish-toggle")
      })
      await waitFor(() => expect(result.current.actionError).toBeTruthy())
      // Optimistic publish reverted after the failure.
      expect(result.current.isPublic).toBe(false)
    })

    it("shows the server message (not an empty guard) on a 422 for a locally-ready clip", async () => {
      // Race: local clip looks ready, but the server rejects (fields changed
      // since load). Recomputing the guard would be all-false → empty prompt;
      // the server's specific message must win instead.
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(
          new Response(
            JSON.stringify({ detail: "Publishing requires a title." }),
            { status: 422 }
          )
        )
      )
      const { result } = setup(ready())

      await act(async () => {
        result.current.handleAction("publish-toggle")
      })
      await waitFor(() =>
        expect(result.current.actionError).toBe("Publishing requires a title.")
      )
      // No empty guard prompt, and the optimistic publish rolled back.
      expect(result.current.publishGuard).toBeNull()
      expect(result.current.isPublic).toBe(false)
    })

    it("unpublishes without guarding, even on an incomplete clip", async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ id: "c1", is_public: false }), {
          status: 200,
        })
      )
      vi.stubGlobal("fetch", fetchMock)
      const { result } = setup(
        clip({ title: null, style_tags: [], is_public: true })
      )
      expect(result.current.isPublic).toBe(true)

      await act(async () => {
        result.current.handleAction("publish-toggle")
      })
      await waitFor(() => expect(result.current.isPublic).toBe(false))
      expect(result.current.publishGuard).toBeNull()
      expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
        is_public: false,
      })
    })
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

  it("calls onDeleted instead of navigating when given (clip-list context)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal("fetch", fetchMock)
    const onDeleted = vi.fn()

    const { result } = setup(clip(), { onDeleted })
    act(() => result.current.handleAction("delete"))
    await act(() => result.current.confirmDelete())

    expect(onDeleted).toHaveBeenCalledWith("c1")
    // The list drops the card itself, so the hook must not navigate home.
    expect(push).not.toHaveBeenCalled()
    // Dialog must close so it can't fire a redundant DELETE on the gone clip.
    expect(result.current.confirmingDelete).toBe(false)
  })

  it("clears a stale download error when the delete dialog opens", async () => {
    // 404 makes the real downloadClipAudio return false and seed actionError.
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response(null, { status: 404 }))
    )
    const { result } = setup()

    act(() => {
      result.current.handleAction("download-mp3")
    })
    await waitFor(() => expect(result.current.actionError).toMatch(/download/i))

    // Opening the delete confirmation must start clean, not show the download error.
    act(() => result.current.handleAction("delete"))
    expect(result.current.actionError).toBeNull()
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
    // Cancelling clears the error so it doesn't linger as a below-menu alert.
    expect(result.current.actionError).toBeNull()
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
