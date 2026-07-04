import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SpeedModal } from "@/components/song/modals/SpeedModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const submitSpeed = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitSpeed: (...args: unknown[]) => submitSpeed(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

describe("SpeedModal", () => {
  it("opens with a mode toggle, multiplier slider and preserve-pitch switch", () => {
    render(<SpeedModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent("Adjust speed")
    expect(screen.getByRole("radio", { name: "By multiplier" })).toBeInTheDocument()
    expect(screen.getByRole("slider")).toBeInTheDocument()
    expect(screen.getByLabelText("Preserve pitch")).toBeChecked()
  })

  it("disables the target-BPM mode when the clip has no BPM", () => {
    render(<SpeedModal clip={makeClip({ bpm: null })} open onClose={vi.fn()} />)
    expect(screen.getByRole("radio", { name: /By target BPM/ })).toBeDisabled()
  })

  it("blocks submit when the target BPM is not a positive number", async () => {
    render(<SpeedModal clip={makeClip({ bpm: 120 })} open onClose={vi.fn()} />)
    await userEvent.click(screen.getByRole("radio", { name: /By target BPM/ }))
    const bpm = screen.getByLabelText("Target BPM")
    await userEvent.clear(bpm)
    await userEvent.type(bpm, "0")
    expect(screen.getByRole("button", { name: "Apply" })).toBeDisabled()
  })

  it("submits a multiplier payload and reaches success", async () => {
    submitSpeed.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["sped-1"] })

    render(<SpeedModal clip={makeClip()} open onClose={vi.fn()} />)
    await userEvent.click(screen.getByRole("button", { name: "Apply" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitSpeed).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({ multiplier: 1, preserve_pitch: true }),
      "tok"
    )
    expect(submitSpeed.mock.calls[0][1]).not.toHaveProperty("target_bpm")
  })

  it("submits a target-BPM payload with only the bpm field", async () => {
    submitSpeed.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["sped-1"] })

    render(<SpeedModal clip={makeClip({ bpm: 120 })} open onClose={vi.fn()} />)
    await userEvent.click(screen.getByRole("radio", { name: /By target BPM/ }))
    const bpm = screen.getByLabelText("Target BPM")
    await userEvent.clear(bpm)
    await userEvent.type(bpm, "90")
    await userEvent.click(screen.getByRole("button", { name: "Apply" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitSpeed).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({ target_bpm: 90, preserve_pitch: true }),
      "tok"
    )
    expect(submitSpeed.mock.calls[0][1]).not.toHaveProperty("multiplier")
  })
})
