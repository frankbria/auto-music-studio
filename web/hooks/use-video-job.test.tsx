import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useVideoJob } from "@/hooks/use-video-job"
import type { VideoConfig } from "@/lib/video"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

const submitVideoJob = vi.fn()
const fetchVideoStatus = vi.fn()
vi.mock("@/lib/video", () => ({
  submitVideoJob: (...a: unknown[]) => submitVideoJob(...a),
  fetchVideoStatus: (...a: unknown[]) => fetchVideoStatus(...a),
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
  return <AuthContext.Provider value={authValue}>{children}</AuthContext.Provider>
}

const config: VideoConfig = {
  prompt: "neon city",
  lyrics_sync: false,
  aspect_ratio: "16:9",
  resolution: "720p",
  frame_rate: 30,
  transitions: "auto",
}

afterEach(() => vi.clearAllMocks())

describe("useVideoJob", () => {
  it("submits, polls, and reaches complete", async () => {
    const detail = { job_id: "j1", status: "complete", progress: 100, video_id: "v1" }
    submitVideoJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchVideoStatus.mockResolvedValue({ kind: "complete", detail })
    const { result } = renderHook(() => useVideoJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    await waitFor(() => expect(result.current.state.phase).toBe("complete"))
    // Token comes from auth context, forwarded to the submit + poll.
    expect(submitVideoJob).toHaveBeenCalledWith("c1", config, "tok")
    expect(fetchVideoStatus).toHaveBeenCalledWith("j1", "tok")
  })

  it("stays in polling with the live detail while the job renders", async () => {
    const detail = { job_id: "j1", status: "rendering", progress: 42, eta_seconds: 90 }
    submitVideoJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchVideoStatus.mockResolvedValue({ kind: "pending", detail })
    const { result } = renderHook(() => useVideoJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    await waitFor(() =>
      expect(result.current.state).toMatchObject({ phase: "polling", detail })
    )
    act(() => result.current.reset())
    expect(result.current.state).toEqual({ phase: "idle" })
  })

  it("surfaces a failed render as an error", async () => {
    submitVideoJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchVideoStatus.mockResolvedValue({ kind: "failed", error: "render died" })
    const { result } = renderHook(() => useVideoJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "error", message: "render died" })
    )
  })

  it("surfaces insufficient credits with a readable message", async () => {
    submitVideoJob.mockResolvedValue({
      status: "insufficient_credits",
      balance: 2,
      required: 5,
    })
    const { result } = renderHook(() => useVideoJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    expect(result.current.state.phase).toBe("error")
    if (result.current.state.phase === "error") {
      expect(result.current.state.message).toMatch(/5 required, 2 available/)
    }
  })

  it("surfaces the 503 unavailable detail verbatim", async () => {
    submitVideoJob.mockResolvedValue({
      status: "unavailable",
      detail: "Video generation is not configured on this deployment.",
    })
    const { result } = renderHook(() => useVideoJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    expect(result.current.state).toEqual({
      phase: "error",
      message: "Video generation is not configured on this deployment.",
    })
  })

  it("redirects to login when submission or a poll is unauthorized", async () => {
    submitVideoJob.mockResolvedValue({ status: "unauthorized" })
    const { result } = renderHook(() => useVideoJob(), { wrapper })
    await act(async () => {
      await result.current.submit("c1", config)
    })
    expect(push).toHaveBeenCalledWith("/login")

    push.mockClear()
    submitVideoJob.mockResolvedValue({ status: "accepted", jobId: "j2" })
    fetchVideoStatus.mockResolvedValue({ kind: "unauthorized" })
    await act(async () => {
      await result.current.submit("c1", config)
    })
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"))
  })

  it("retry replays the last submission", async () => {
    submitVideoJob.mockResolvedValue({ status: "error", detail: "boom" })
    const { result } = renderHook(() => useVideoJob(), { wrapper })
    await act(async () => {
      await result.current.submit("c1", config)
    })
    expect(result.current.state).toEqual({ phase: "error", message: "boom" })

    submitVideoJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchVideoStatus.mockResolvedValue({
      kind: "pending",
      detail: { job_id: "j1", status: "queued", progress: 0 },
    })
    await act(async () => {
      result.current.retry()
    })
    await waitFor(() => expect(result.current.state.phase).toBe("polling"))
    expect(submitVideoJob).toHaveBeenLastCalledWith("c1", config, "tok")
    act(() => result.current.reset())
  })
})
