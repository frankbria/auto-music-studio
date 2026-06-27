import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useGeneration } from "@/hooks/use-generation"
import type { SubmitResult } from "@/lib/generate"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

const make = (result: SubmitResult) => vi.fn().mockResolvedValue(result)

describe("useGeneration", () => {
  it("submits, polls, and reaches success — calling onComplete with the clips", async () => {
    const onComplete = vi.fn()
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["c1", "c2"],
    })
    const { result } = renderHook(() => useGeneration({ onComplete }))

    await act(async () => {
      await result.current.submit(
        make({ status: "accepted", jobId: "j1", estimatedSeconds: 12 }),
        "tok"
      )
    })

    await waitFor(() => expect(result.current.state.phase).toBe("success"))
    expect(result.current.state).toEqual({
      phase: "success",
      clipIds: ["c1", "c2"],
    })
    expect(onComplete).toHaveBeenCalledOnce()
    expect(fetchJobStatus).toHaveBeenCalledWith("j1", "tok")
  })

  it("exposes the backend time estimate while polling", async () => {
    fetchJobStatus.mockResolvedValue({ kind: "pending" })
    const { result } = renderHook(() => useGeneration())

    await act(async () => {
      await result.current.submit(
        make({ status: "accepted", jobId: "j1", estimatedSeconds: 30 }),
        "tok"
      )
    })

    expect(result.current.state).toMatchObject({
      phase: "polling",
      estimatedSeconds: 30,
    })
    act(() => result.current.reset())
  })

  it("surfaces a failed job as an error", async () => {
    fetchJobStatus.mockResolvedValue({ kind: "failed", error: "boom" })
    const { result } = renderHook(() => useGeneration())

    await act(async () => {
      await result.current.submit(
        make({ status: "accepted", jobId: "j1", estimatedSeconds: 5 }),
        "tok"
      )
    })

    await waitFor(() =>
      expect(result.current.state).toEqual({ phase: "error", message: "boom" })
    )
  })

  it("surfaces a rejected submission (422/error) as an error", async () => {
    const { result } = renderHook(() => useGeneration())
    await act(async () => {
      await result.current.submit(
        make({ status: "invalid", detail: "bad input" }),
        "tok"
      )
    })
    expect(result.current.state).toEqual({
      phase: "error",
      message: "bad input",
    })
  })

  it("redirects to login when submission is unauthorized", async () => {
    const { result } = renderHook(() => useGeneration())
    await act(async () => {
      await result.current.submit(make({ status: "unauthorized" }), "tok")
    })
    expect(push).toHaveBeenCalledWith("/login")
  })

  it("redirects to login when a poll returns unauthorized", async () => {
    fetchJobStatus.mockResolvedValue({ kind: "unauthorized" })
    const { result } = renderHook(() => useGeneration())
    await act(async () => {
      await result.current.submit(
        make({ status: "accepted", jobId: "j1", estimatedSeconds: 5 }),
        "tok"
      )
    })
    await waitFor(() => expect(push).toHaveBeenCalledWith("/login"))
  })

  it("retry replays the last submission", async () => {
    fetchJobStatus.mockResolvedValue({ kind: "failed", error: "boom" })
    const submitFn = make({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 5,
    })
    const { result } = renderHook(() => useGeneration())

    await act(async () => {
      await result.current.submit(submitFn, "tok")
    })
    await waitFor(() => expect(result.current.state.phase).toBe("error"))

    await act(async () => {
      result.current.retry()
    })
    expect(submitFn).toHaveBeenCalledTimes(2)
  })

  it("reset returns to idle", async () => {
    const { result } = renderHook(() => useGeneration())
    await act(async () => {
      await result.current.submit(make({ status: "error", detail: "x" }), "tok")
    })
    expect(result.current.state.phase).toBe("error")
    act(() => result.current.reset())
    expect(result.current.state).toEqual({ phase: "idle" })
  })
})
