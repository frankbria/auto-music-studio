import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ReplaceSectionModal } from "@/components/song/modals/ReplaceSectionModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const submitRepaint = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitRepaint: (...args: unknown[]) => submitRepaint(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

describe("ReplaceSectionModal", () => {
  it("opens with range + instruction controls", () => {
    render(<ReplaceSectionModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent("Replace section")
    expect(screen.getByLabelText("Start")).toBeInTheDocument()
    expect(screen.getByLabelText("End")).toBeInTheDocument()
    expect(screen.getByLabelText(/Replacement instructions/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Style/)).toBeInTheDocument()
  })

  it("disables submit until replacement instructions are provided", async () => {
    render(<ReplaceSectionModal clip={makeClip({ duration: 60 })} open onClose={vi.fn()} />)
    expect(screen.getByRole("button", { name: "Replace" })).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Replacement instructions/), "make it jazzy")
    expect(screen.getByRole("button", { name: "Replace" })).toBeEnabled()
  })

  it("submits the repaint payload to the repaint endpoint and reaches success", async () => {
    submitRepaint.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["repainted-1"] })

    render(<ReplaceSectionModal clip={makeClip({ duration: 60 })} open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/Replacement instructions/), "make it jazzy")
    await userEvent.click(screen.getByRole("button", { name: "Replace" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitRepaint).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({ start: "0s", end: "60s", prompt: "make it jazzy" }),
      "tok"
    )
  })
})
