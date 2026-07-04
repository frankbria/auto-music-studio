import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { useClipEdit } from "@/hooks/use-clip-edit"
import type { EditSubmitResult } from "@/lib/editing"

const push = vi.fn()
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

const make = (result: EditSubmitResult) => vi.fn().mockResolvedValue(result)

describe("useClipEdit", () => {
  it("submits, polls, and surfaces the resulting clip ids on success", async () => {
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["new-1"] })
    const { result } = renderHook(() => useClipEdit())

    await act(async () => {
      await result.current.submit(
        make({ status: "accepted", jobId: "j1", estimatedSeconds: 45 }),
        "tok"
      )
    })

    await waitFor(() => expect(result.current.state.phase).toBe("success"))
    expect(result.current.state).toEqual({ phase: "success", clipIds: ["new-1"] })
    expect(fetchJobStatus).toHaveBeenCalledWith("j1", "tok")
  })

  it("holds a polling state with the time estimate", async () => {
    fetchJobStatus.mockResolvedValue({ kind: "pending" })
    const { result } = renderHook(() => useClipEdit())

    await act(async () => {
      await result.current.submit(
        make({ status: "accepted", jobId: "j1", estimatedSeconds: 30 }),
        "tok"
      )
    })

    expect(result.current.state).toMatchObject({ phase: "polling", estimatedSeconds: 30 })
    act(() => result.current.reset())
    expect(result.current.state.phase).toBe("idle")
  })

  it("maps insufficient credits to an actionable error", async () => {
    const { result } = renderHook(() => useClipEdit())
    await act(async () => {
      await result.current.submit(
        make({ status: "insufficientCredits", balance: 1, required: 4 }),
        "tok"
      )
    })
    expect(result.current.state).toEqual({
      phase: "error",
      message: "Not enough credits — this needs 4, you have 1.",
    })
  })

  it("surfaces a validation error without polling", async () => {
    const { result } = renderHook(() => useClipEdit())
    await act(async () => {
      await result.current.submit(
        make({ status: "invalid", detail: "start must be before end" }),
        "tok"
      )
    })
    expect(result.current.state).toEqual({
      phase: "error",
      message: "start must be before end",
    })
    expect(fetchJobStatus).not.toHaveBeenCalled()
  })

  it("surfaces a failed job", async () => {
    fetchJobStatus.mockResolvedValue({ kind: "failed", error: "edit failed" })
    const { result } = renderHook(() => useClipEdit())
    await act(async () => {
      await result.current.submit(
        make({ status: "accepted", jobId: "j1", estimatedSeconds: 0 }),
        "tok"
      )
    })
    await waitFor(() => expect(result.current.state.phase).toBe("error"))
    expect(result.current.state).toMatchObject({ message: "edit failed" })
  })

  it("redirects to login when the submit is unauthorized", async () => {
    const { result } = renderHook(() => useClipEdit())
    await act(async () => {
      await result.current.submit(make({ status: "unauthorized" }), "tok")
    })
    expect(push).toHaveBeenCalledWith("/login")
  })

  it("retries the last submission", async () => {
    fetchJobStatus.mockResolvedValue({ kind: "pending" })
    const submitFn = make({ status: "accepted", jobId: "j1", estimatedSeconds: 5 })
    const { result } = renderHook(() => useClipEdit())

    await act(async () => {
      await result.current.submit(submitFn, "tok")
    })
    act(() => result.current.retry())
    await waitFor(() => expect(submitFn).toHaveBeenCalledTimes(2))
    act(() => result.current.reset())
  })
})
