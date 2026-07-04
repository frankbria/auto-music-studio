import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ExtendModal } from "@/components/song/modals/ExtendModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const submitExtend = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitExtend: (...args: unknown[]) => submitExtend(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

describe("ExtendModal", () => {
  it("opens with an extension-point selector and duration + optional fields", () => {
    render(<ExtendModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent("Extend")
    expect(screen.getByLabelText("From end")).toBeInTheDocument()
    expect(screen.getByLabelText("At timestamp")).toBeInTheDocument()
    expect(screen.getByLabelText("Duration")).toBeInTheDocument()
    expect(screen.getByLabelText("Style override")).toBeInTheDocument()
    expect(screen.getByLabelText("Lyrics continuation")).toBeInTheDocument()
  })

  it("disables submit until a duration is entered", () => {
    render(<ExtendModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("button", { name: "Extend" })).toBeDisabled()
  })

  it("submits the extend payload from the end and reaches success", async () => {
    submitExtend.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["extended-1"] })

    render(<ExtendModal clip={makeClip()} open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText("Duration"), "45s")
    await userEvent.click(screen.getByRole("button", { name: "Extend" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitExtend).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({ duration: "45s", from_point: "end" }),
      "tok"
    )
  })
})
