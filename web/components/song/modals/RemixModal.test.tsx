import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { RemixModal } from "@/components/song/modals/RemixModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const submitRemix = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitRemix: (...args: unknown[]) => submitRemix(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

describe("RemixModal", () => {
  it("opens with a required style field and a credit hint", () => {
    render(<RemixModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent("Remix")
    expect(screen.getByLabelText(/New style/)).toBeInTheDocument()
    expect(screen.getByText("Uses 1 credit")).toBeInTheDocument()
  })

  it("disables submit until a non-empty style is entered", async () => {
    render(<RemixModal clip={makeClip()} open onClose={vi.fn()} />)
    const remix = screen.getByRole("button", { name: "Remix" })
    expect(remix).toBeDisabled()

    await userEvent.type(screen.getByLabelText(/New style/), "   ")
    expect(remix).toBeDisabled()

    await userEvent.type(screen.getByLabelText(/New style/), "synthwave")
    expect(remix).toBeEnabled()
  })

  it("submits the style payload and reaches success", async () => {
    submitRemix.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["remix-1"] })

    render(<RemixModal clip={makeClip()} open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/New style/), "80s synthwave")
    await userEvent.click(screen.getByRole("button", { name: "Remix" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitRemix).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({ style: "80s synthwave" }),
      "tok"
    )
  })
})
