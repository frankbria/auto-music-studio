import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SampleModal } from "@/components/song/modals/SampleModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const submitSample = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitSample: (...args: unknown[]) => submitSample(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

describe("SampleModal", () => {
  it("renders the range, role radios, prompt, and clip-count controls", () => {
    render(<SampleModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent("Sample from song")
    expect(screen.getByLabelText("Start")).toBeInTheDocument()
    expect(screen.getByLabelText("End")).toBeInTheDocument()
    expect(screen.getByLabelText("Loop bed")).toBeInTheDocument()
    expect(screen.getByLabelText("Intro / outro")).toBeInTheDocument()
    expect(screen.getByLabelText("Rhythmic element")).toBeInTheDocument()
    expect(screen.getByLabelText("Melodic hook")).toBeInTheDocument()
    expect(screen.getByLabelText(/Prompt/)).toBeInTheDocument()
    expect(screen.getByText("Number of clips")).toBeInTheDocument()
  })

  it("disables submit while the prompt is empty", () => {
    render(<SampleModal clip={makeClip({ duration: 60 })} open onClose={vi.fn()} />)
    expect(screen.getByRole("button", { name: "Create sample" })).toBeDisabled()
  })

  it("updates the credit hint when the clip count changes", async () => {
    render(<SampleModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByText("Uses 1 credit")).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText("3"))
    expect(screen.getByText("Uses 3 credits")).toBeInTheDocument()
  })

  it("submits the sample payload and reaches success", async () => {
    submitSample.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["sample-1", "sample-2"] })

    render(<SampleModal clip={makeClip({ duration: 60 })} open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/Prompt/), "warm vinyl loop")
    await userEvent.click(screen.getByLabelText("Melodic hook"))
    await userEvent.click(screen.getByLabelText("2"))
    await userEvent.click(screen.getByRole("button", { name: "Create sample" }))

    await waitFor(() =>
      expect(screen.getByText("2 new clips are ready.")).toBeInTheDocument()
    )
    expect(submitSample).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({
        start: "0s",
        end: "60s",
        role: "melodic-hook",
        prompt: "warm vinyl loop",
        num_clips: 2,
      }),
      "tok"
    )
  })
})
