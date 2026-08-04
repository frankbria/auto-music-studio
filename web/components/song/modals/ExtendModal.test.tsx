import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { ExtendModal } from "@/components/song/modals/ExtendModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({
    accessToken: "tok",
    isLoading: false,
    isAuthenticated: true,
  }),
}))

const submitExtend = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitExtend: (...args: unknown[]) => submitExtend(...args),
}))

// The Add Voice control reads the musician's real library (US-25.4).
vi.mock("@/hooks/use-voice-models", () => ({
  useVoiceModels: () => ({
    state: {
      phase: "ready",
      models: [
        {
          id: "v1",
          name: "Aria",
          description: "Warm and breathy",
          status: "ready",
          reference_count: 3,
          job_id: null,
          error: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    },
  }),
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
    submitExtend.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["extended-1"],
    })

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

  it("blocks an extend that would exceed the 240s generation cap", async () => {
    // 200s clip + a 60s extension from the end = 260s > DURATION_MAX (240s).
    render(
      <ExtendModal clip={makeClip({ duration: 200 })} open onClose={vi.fn()} />
    )
    await userEvent.type(screen.getByLabelText("Duration"), "60s")

    expect(screen.getByText(/can't exceed 240s/)).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Extend" })).toBeDisabled()
    expect(submitExtend).not.toHaveBeenCalled()
  })
  it("sends the attached voice (US-25.4)", async () => {
    submitExtend.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["ext-1"] })

    render(<ExtendModal clip={makeClip()} open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/Duration/), "20s")
    await userEvent.click(screen.getByRole("button", { name: /add voice/i }))
    await userEvent.click(screen.getByRole("button", { name: /aria/i }))
    await userEvent.click(screen.getByRole("button", { name: "Extend" }))

    await waitFor(() => expect(submitExtend).toHaveBeenCalled())
    expect(submitExtend.mock.calls[0][1]).toMatchObject({
      voice_model_id: "v1",
    })
  })
})
