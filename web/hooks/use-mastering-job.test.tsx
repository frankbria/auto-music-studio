import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { ReactNode } from "react"

import { AuthContext } from "@/contexts/auth-context"
import { useMasteringJob } from "@/hooks/use-mastering-job"
import type { MasteringConfig } from "@/lib/mastering"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

const submitMasteringJob = vi.fn()
const fetchMasteringStatus = vi.fn()
vi.mock("@/lib/mastering", () => ({
  submitMasteringJob: (...a: unknown[]) => submitMasteringJob(...a),
  fetchMasteringStatus: (...a: unknown[]) => fetchMasteringStatus(...a),
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

const config: MasteringConfig = { profile: "streaming", service: "dolby", format: "wav" }

afterEach(() => vi.clearAllMocks())

describe("useMasteringJob", () => {
  it("submits, polls, and reaches completed — calling onComplete with the detail", async () => {
    const detail = { job_id: "j1", status: "completed", mastered_clip_id: "m1" }
    const onComplete = vi.fn()
    submitMasteringJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchMasteringStatus.mockResolvedValue({ kind: "completed", detail })
    const { result } = renderHook(() => useMasteringJob({ onComplete }), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    await waitFor(() => expect(result.current.state.phase).toBe("completed"))
    expect(onComplete).toHaveBeenCalledWith(detail)
    // Token comes from auth context, forwarded to the submit + poll.
    expect(submitMasteringJob).toHaveBeenCalledWith("c1", config, "tok")
    expect(fetchMasteringStatus).toHaveBeenCalledWith("j1", "tok")
  })

  it("stays in polling while the job is queued/processing", async () => {
    submitMasteringJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchMasteringStatus.mockResolvedValue({
      kind: "pending",
      detail: { job_id: "j1", status: "processing" },
    })
    const { result } = renderHook(() => useMasteringJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    expect(result.current.state).toMatchObject({ phase: "polling" })
    act(() => result.current.reset())
  })

  it("surfaces a failed job as an error", async () => {
    submitMasteringJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchMasteringStatus.mockResolvedValue({ kind: "failed", error: "boom" })
    const { result } = renderHook(() => useMasteringJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "error", message: "boom" })
    )
  })

  it("surfaces insufficient credits with a readable message", async () => {
    submitMasteringJob.mockResolvedValue({
      status: "insufficient_credits",
      balance: 1,
      required: 3,
    })
    const { result } = renderHook(() => useMasteringJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })

    expect(result.current.state.phase).toBe("error")
    if (result.current.state.phase === "error") {
      expect(result.current.state.message).toMatch(/3 required, 1 available/)
    }
  })

  it("redirects to login when submission is unauthorized", async () => {
    submitMasteringJob.mockResolvedValue({ status: "unauthorized" })
    const { result } = renderHook(() => useMasteringJob(), { wrapper })
    await act(async () => {
      await result.current.submit("c1", config)
    })
    expect(push).toHaveBeenCalledWith("/login")
  })

  it("redirects to login when a poll returns unauthorized", async () => {
    submitMasteringJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchMasteringStatus.mockResolvedValue({ kind: "unauthorized" })
    const { result } = renderHook(() => useMasteringJob(), { wrapper })
    await act(async () => {
      await result.current.submit("c1", config)
    })
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"))
  })

  it("retry replays the last submission", async () => {
    submitMasteringJob.mockResolvedValue({ status: "accepted", jobId: "j1" })
    fetchMasteringStatus.mockResolvedValue({ kind: "failed", error: "boom" })
    const { result } = renderHook(() => useMasteringJob(), { wrapper })

    await act(async () => {
      await result.current.submit("c1", config)
    })
    await waitFor(() => expect(result.current.state.phase).toBe("error"))

    await act(async () => {
      result.current.retry()
    })
    expect(submitMasteringJob).toHaveBeenCalledTimes(2)
    expect(submitMasteringJob).toHaveBeenLastCalledWith("c1", config, "tok")
  })

  it("reset returns to idle", async () => {
    submitMasteringJob.mockResolvedValue({ status: "error", detail: "x" })
    const { result } = renderHook(() => useMasteringJob(), { wrapper })
    await act(async () => {
      await result.current.submit("c1", config)
    })
    expect(result.current.state.phase).toBe("error")
    act(() => result.current.reset())
    expect(result.current.state).toEqual({ phase: "idle" })
  })
})
