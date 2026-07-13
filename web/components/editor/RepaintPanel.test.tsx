import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { RepaintPanel } from "@/components/editor/RepaintPanel"
import type { ClipAudio } from "@/lib/audio-peaks"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({
    accessToken: "tok",
    isLoading: false,
    isAuthenticated: true,
  }),
}))

const submitRepaint = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitRepaint: (...args: unknown[]) => submitRepaint(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

const decodeClipAudio = vi.fn()
vi.mock("@/lib/audio-peaks", () => ({
  decodeClipAudio: (...args: unknown[]) => decodeClipAudio(...args),
}))

const CHILD_AUDIO = {
  mono: new Float32Array([0.1, 0.2, 0.3]),
  sampleRate: 44100,
  duration: 30,
} as unknown as ClipAudio

afterEach(() => vi.clearAllMocks())

const selection = { startSec: 15, endSec: 30 }

describe("RepaintPanel", () => {
  it("shows the repaint heading and the instruction + style fields", () => {
    render(
      <RepaintPanel
        selection={selection}
        clipId="clip-1"
        onRepainted={vi.fn()}
      />
    )
    expect(screen.getByTestId("repaint-panel")).toHaveTextContent(
      "Repaint selection"
    )
    expect(screen.getByLabelText(/Instructions/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Style/)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Regenerate" })
    ).toBeInTheDocument()
  })

  it("disables Regenerate until instructions are provided", async () => {
    render(
      <RepaintPanel
        selection={selection}
        clipId="clip-1"
        onRepainted={vi.fn()}
      />
    )
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Instructions/), "make it jazzy")
    expect(screen.getByRole("button", { name: "Regenerate" })).toBeEnabled()
  })

  it("submits the repaint with Ns coords and applies the decoded child on success", async () => {
    submitRepaint.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["child-1"],
    })
    decodeClipAudio.mockResolvedValue(CHILD_AUDIO)
    const onRepainted = vi.fn()

    render(
      <RepaintPanel
        selection={selection}
        clipId="clip-1"
        onRepainted={onRepainted}
      />
    )
    await userEvent.type(screen.getByLabelText(/Instructions/), "make it jazzy")
    await userEvent.type(screen.getByLabelText(/Style/), "lofi")
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }))

    await waitFor(() => expect(onRepainted).toHaveBeenCalled())

    expect(submitRepaint).toHaveBeenCalledWith(
      "clip-1",
      { start: "15s", end: "30s", prompt: "make it jazzy", style: "lofi" },
      "tok"
    )
    expect(decodeClipAudio).toHaveBeenCalledWith("child-1", "tok")
    expect(onRepainted).toHaveBeenCalledWith(CHILD_AUDIO, {
      kind: "repaint",
      startSec: 15,
      endSec: 30,
      prompt: "make it jazzy",
      style: "lofi",
    })
  })

  it("retries only the decode (no resubmit) after the job succeeded but the fetch failed", async () => {
    submitRepaint.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["child-1"],
    })
    // First decode fails (network blip on the already-generated clip), then succeeds.
    decodeClipAudio
      .mockRejectedValueOnce(new Error("net"))
      .mockResolvedValueOnce(CHILD_AUDIO)
    const onRepainted = vi.fn()

    render(
      <RepaintPanel
        selection={selection}
        clipId="clip-1"
        onRepainted={onRepainted}
      />
    )
    await userEvent.type(screen.getByLabelText(/Instructions/), "make it jazzy")
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }))

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        /Couldn't load the repainted audio/
      )
    )
    expect(submitRepaint).toHaveBeenCalledTimes(1)

    await userEvent.click(screen.getByRole("button", { name: "Try again" }))
    await waitFor(() => expect(onRepainted).toHaveBeenCalled())

    // Retry re-fetched the same child; it did NOT start a new (paid) generation.
    expect(submitRepaint).toHaveBeenCalledTimes(1)
    expect(decodeClipAudio).toHaveBeenCalledTimes(2)
    expect(decodeClipAudio).toHaveBeenLastCalledWith("child-1", "tok")
  })

  it("reports active continuously from submit through decode — no transient false when the job succeeds", async () => {
    // Pre-existing Stage-18 race (found via a full-render flake during #207):
    // `active` used to drop true→false for one render between the poll hitting
    // "success" and `applying` flipping true, since the apply effect that sets
    // `applying` runs after the onActiveChange effect that reads it. Holding
    // decodeClipAudio pending lets this test observe that gap deterministically
    // instead of relying on the timing-sensitive full WaveformEditor render.
    submitRepaint.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["child-1"],
    })
    let resolveDecode: (a: unknown) => void = () => {}
    decodeClipAudio.mockReturnValue(
      new Promise((res) => {
        resolveDecode = res
      })
    )
    const onActiveChange = vi.fn()

    render(
      <RepaintPanel
        selection={selection}
        clipId="clip-1"
        onRepainted={vi.fn()}
        onActiveChange={onActiveChange}
      />
    )
    await userEvent.type(screen.getByLabelText(/Instructions/), "make it jazzy")
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }))

    // Job succeeded, decode is in flight (held above) — "Applying…" is up.
    await waitFor(() =>
      expect(screen.getByText(/Applying/)).toBeInTheDocument()
    )

    const firstTrue = onActiveChange.mock.calls.findIndex((c) => c[0] === true)
    expect(firstTrue).toBeGreaterThanOrEqual(0)
    const sinceFirstTrue = onActiveChange.mock.calls.slice(firstTrue)
    expect(sinceFirstTrue.every((c) => c[0] === true)).toBe(true)

    // Decode resolves: active must still correctly drop to false once applied.
    resolveDecode(CHILD_AUDIO)
    await waitFor(() => expect(onActiveChange).toHaveBeenLastCalledWith(false))
  })

  it("surfaces a failed job and offers retry, without applying anything", async () => {
    submitRepaint.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "failed",
      error: "Generation failed.",
    })
    const onRepainted = vi.fn()

    render(
      <RepaintPanel
        selection={selection}
        clipId="clip-1"
        onRepainted={onRepainted}
      />
    )
    await userEvent.type(screen.getByLabelText(/Instructions/), "make it jazzy")
    await userEvent.click(screen.getByRole("button", { name: "Regenerate" }))

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Generation failed.")
    )
    expect(
      screen.getByRole("button", { name: "Try again" })
    ).toBeInTheDocument()
    expect(onRepainted).not.toHaveBeenCalled()
    expect(decodeClipAudio).not.toHaveBeenCalled()
  })
})
