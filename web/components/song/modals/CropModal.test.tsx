import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CropModal } from "@/components/song/modals/CropModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const submitCrop = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitCrop: (...args: unknown[]) => submitCrop(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

describe("CropModal", () => {
  it("opens with range + fade controls and a beat-snap toggle", () => {
    render(<CropModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent("Crop")
    expect(screen.getByLabelText("Start")).toBeInTheDocument()
    expect(screen.getByLabelText("End")).toBeInTheDocument()
    expect(screen.getByLabelText("Fade in")).toBeInTheDocument()
    expect(screen.getByLabelText(/Snap to beat/)).toBeEnabled()
  })

  it("disables the snap toggle when the clip has no BPM", () => {
    render(<CropModal clip={makeClip({ bpm: null })} open onClose={vi.fn()} />)
    expect(screen.getByLabelText(/Snap to beat/)).toBeDisabled()
  })

  it("blocks submit when start is not before end", async () => {
    render(<CropModal clip={makeClip({ duration: 60 })} open onClose={vi.fn()} />)
    const start = screen.getByLabelText("Start")
    await userEvent.clear(start)
    await userEvent.type(start, "90s")
    expect(screen.getByRole("button", { name: "Crop" })).toBeDisabled()
  })

  it("submits the crop payload to the crop endpoint and reaches success", async () => {
    submitCrop.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["cropped-1"] })

    render(<CropModal clip={makeClip({ duration: 60 })} open onClose={vi.fn()} />)
    const end = screen.getByLabelText("End")
    await userEvent.clear(end)
    await userEvent.type(end, "30s")
    await userEvent.click(screen.getByRole("button", { name: "Crop" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitCrop).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({ start: "0s", end: "30s", snap_to_beat: false }),
      "tok"
    )
  })

  it("retry resubmits with corrected field values, not the stale payload", async () => {
    // First attempt fails at the backend; the user then fixes the range and
    // retries. Try again must send the current values, not the original ones.
    submitCrop.mockResolvedValue({ status: "invalid", detail: "bad range" })

    render(<CropModal clip={makeClip({ duration: 60 })} open onClose={vi.fn()} />)
    const end = screen.getByLabelText("End")
    await userEvent.clear(end)
    await userEvent.type(end, "20s")
    await userEvent.click(screen.getByRole("button", { name: "Crop" }))

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("bad range"))
    expect(submitCrop).toHaveBeenLastCalledWith(
      "clip-1",
      expect.objectContaining({ end: "20s" }),
      "tok"
    )

    // Correct the field, then retry — the resubmission carries the new value.
    // Re-query: the form remounts after the spinner, so the earlier node is stale.
    submitCrop.mockResolvedValue({ status: "accepted", jobId: "j2", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["cropped-2"] })
    const endAfterError = screen.getByLabelText("End")
    await userEvent.clear(endAfterError)
    await userEvent.type(endAfterError, "45s")
    await userEvent.click(screen.getByRole("button", { name: "Try again" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitCrop).toHaveBeenLastCalledWith(
      "clip-1",
      expect.objectContaining({ end: "45s" }),
      "tok"
    )
  })
})
