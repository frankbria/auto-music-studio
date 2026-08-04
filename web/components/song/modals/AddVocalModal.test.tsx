import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { AddVocalModal } from "@/components/song/modals/AddVocalModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({
    accessToken: "tok",
    isLoading: false,
    isAuthenticated: true,
  }),
}))

const submitAddVocal = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitAddVocal: (...args: unknown[]) => submitAddVocal(...args),
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

describe("AddVocalModal", () => {
  it("opens with lyrics + vocal-style controls", () => {
    render(<AddVocalModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("dialog")).toHaveTextContent("Add vocal")
    expect(screen.getByLabelText(/Lyrics/)).toBeInTheDocument()
    expect(screen.getByLabelText(/Vocal style/)).toBeInTheDocument()
  })

  it("disables submit until lyrics are provided", async () => {
    render(<AddVocalModal clip={makeClip()} open onClose={vi.fn()} />)
    expect(screen.getByRole("button", { name: "Add vocal" })).toBeDisabled()
    await userEvent.type(screen.getByLabelText(/Lyrics/), "la la la")
    expect(screen.getByRole("button", { name: "Add vocal" })).toBeEnabled()
  })

  it("submits the add-vocal payload to the add-vocal endpoint and reaches success", async () => {
    submitAddVocal.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["voiced-1"],
    })

    render(<AddVocalModal clip={makeClip()} open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/Lyrics/), "la la la")
    await userEvent.click(screen.getByRole("button", { name: "Add vocal" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitAddVocal).toHaveBeenCalledWith(
      "clip-1",
      expect.objectContaining({ lyrics: "la la la" }),
      "tok"
    )
  })
  it("sends the attached voice (US-25.4)", async () => {
    submitAddVocal.mockResolvedValue({
      status: "accepted",
      jobId: "j1",
      estimatedSeconds: 0,
    })
    fetchJobStatus.mockResolvedValue({
      kind: "completed",
      clipIds: ["vocal-1"],
    })

    render(<AddVocalModal clip={makeClip()} open onClose={vi.fn()} />)
    await userEvent.type(screen.getByLabelText(/Lyrics/), "[Verse]\nla la la")
    await userEvent.click(screen.getByRole("button", { name: /add voice/i }))
    await userEvent.click(screen.getByRole("button", { name: /aria/i }))
    await userEvent.click(screen.getByRole("button", { name: "Add vocal" }))

    await waitFor(() => expect(submitAddVocal).toHaveBeenCalled())
    expect(submitAddVocal.mock.calls[0][1]).toMatchObject({
      voice_model_id: "v1",
    })
  })
})
