import { renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useVoiceTraining } from "@/hooks/use-voice-training"
import type { VoiceTrainingStatus } from "@/lib/voice-models"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok-1" }),
}))

vi.mock("@/lib/voice-models", async () => {
  const actual = await vi.importActual<typeof import("@/lib/voice-models")>("@/lib/voice-models")
  return { ...actual, fetchTrainingStatus: vi.fn() }
})

import { fetchTrainingStatus, VoiceModelError } from "@/lib/voice-models"

const mockFetch = vi.mocked(fetchTrainingStatus)

function status(overrides: Partial<VoiceTrainingStatus> = {}): VoiceTrainingStatus {
  return {
    job_id: "job-1",
    voice_model_id: "vm-1",
    status: "training",
    phase: "training",
    progress: 50,
    eta_seconds: 30,
    step: 5,
    epoch: 1,
    loss: 0.4,
    error: null,
    ...overrides,
  }
}

beforeEach(() => {
  mockFetch.mockReset()
})

afterEach(() => {
  vi.useRealTimers()
})

describe("useVoiceTraining", () => {
  it("reports progress while a run is in flight", async () => {
    mockFetch.mockResolvedValue(status())

    const { result } = renderHook(() => useVoiceTraining("job-1"))

    await waitFor(() => expect(result.current.state.phase).toBe("polling"))
    expect(result.current.state).toMatchObject({
      phase: "polling",
      status: { progress: 50, eta_seconds: 30 },
    })
  })

  it("stops polling once the run settles", async () => {
    mockFetch.mockResolvedValue(status({ status: "ready", phase: "complete", progress: 100 }))

    const onSettled = vi.fn()
    const { result } = renderHook(() => useVoiceTraining("job-1", { onSettled }))

    await waitFor(() => expect(result.current.state.phase).toBe("settled"))
    expect(onSettled).toHaveBeenCalledTimes(1)

    // A settled run must not keep polling: one read, and no more however long we wait.
    const callsAfterSettling = mockFetch.mock.calls.length
    await new Promise((resolve) => setTimeout(resolve, 50))
    expect(mockFetch.mock.calls.length).toBe(callsAfterSettling)
  })

  it("AC: progress is restored after navigating away and back", async () => {
    // The criterion exists to catch a client-side tally that a remount destroys.
    // Progress lives on the server, so a fresh mount re-reads it.
    mockFetch.mockResolvedValue(status({ progress: 70, step: 7 }))

    const first = renderHook(() => useVoiceTraining("job-1"))
    await waitFor(() => expect(first.result.current.state.phase).toBe("polling"))
    first.unmount()

    const second = renderHook(() => useVoiceTraining("job-1"))
    await waitFor(() => expect(second.result.current.state.phase).toBe("polling"))

    expect(second.result.current.state).toMatchObject({
      phase: "polling",
      status: { progress: 70, step: 7 },
    })
  })

  it("surfaces a failed run with its reason rather than a bare error", async () => {
    mockFetch.mockResolvedValue(
      status({ status: "failed", phase: "failed", progress: null, error: "CUDA out of memory" })
    )

    const { result } = renderHook(() => useVoiceTraining("job-1"))

    await waitFor(() => expect(result.current.state.phase).toBe("settled"))
    expect(result.current.state).toMatchObject({
      phase: "settled",
      status: { status: "failed", error: "CUDA out of memory" },
    })
  })

  it("reports a lookup failure without pretending the run is progressing", async () => {
    mockFetch.mockRejectedValue(new VoiceModelError("Training job not found.", 404))

    const { result } = renderHook(() => useVoiceTraining("job-1"))

    await waitFor(() => expect(result.current.state.phase).toBe("error"))
    expect(result.current.state).toMatchObject({ message: "Training job not found." })
  })

  it("does nothing without a job", async () => {
    const { result } = renderHook(() => useVoiceTraining(null))
    expect(result.current.state.phase).toBe("idle")
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it("a null progress is passed through, not turned into zero", async () => {
    // ACE-Step cannot always report a total. Rendering 0 would read as "stuck",
    // so the null has to survive the hook for the UI to show "working" instead.
    mockFetch.mockResolvedValue(status({ progress: null }))

    const { result } = renderHook(() => useVoiceTraining("job-1"))

    await waitFor(() => expect(result.current.state.phase).toBe("polling"))
    expect(
      result.current.state.phase === "polling" ? result.current.state.status.progress : "missing"
    ).toBeNull()
  })
})
