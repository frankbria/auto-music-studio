import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { CoverModal } from "@/components/song/modals/CoverModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const submitCover = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitCover: (...args: unknown[]) => submitCover(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

describe("CoverModal", () => {
  it("opens with target-style and optional lyrics fields", () => {
    render(<CoverModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent("Cover")
    expect(screen.getByLabelText(/Target style/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Lyrics override/)).toBeInTheDocument()
  })

  it("disables submit until a target style is entered", () => {
    render(<CoverModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("button", { name: "Create cover" })).toBeDisabled()
  })

  it("submits the cover payload and reaches success", async () => {
    submitCover.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["cover-1"] })

    render(<CoverModal clip={makeClip()} open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/Target style/), "acoustic ballad")
    await userEvent.click(screen.getByRole("button", { name: "Create cover" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitCover).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({ style: "acoustic ballad" }),
      "tok"
    )
  })
})
