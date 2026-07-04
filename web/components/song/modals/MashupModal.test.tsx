import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { MashupModal } from "@/components/song/modals/MashupModal"
import { makeClip } from "@/test/clip-factory"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const submitMashup = vi.fn()
vi.mock("@/lib/editing", () => ({
  submitMashup: (...args: unknown[]) => submitMashup(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

const useClips = vi.fn()
vi.mock("@/hooks/use-clips", () => ({
  useClips: (...args: unknown[]) => useClips(...args),
}))

afterEach(() => vi.clearAllMocks())

const clip = makeClip({ id: "clip-1", title: "Primary", workspace_id: "ws-1" })

function mockEligibleClips() {
  useClips.mockReturnValue({
    data: {
      clips: [
        clip,
        makeClip({ id: "clip-2", title: "Second" }),
        makeClip({ id: "clip-3", title: "Third" }),
      ],
    },
    loading: false,
    error: false,
  })
}

describe("MashupModal", () => {
  it("blocks submit until at least two clips are selected", () => {
    mockEligibleClips()
    render(<MashupModal clip={clip} open onClose={vi.fn()} />)
    expect(screen.getByRole("button", { name: "Create mashup" })).toBeDisabled()
  })

  it("enables submit once a second eligible clip is picked", async () => {
    mockEligibleClips()
    render(<MashupModal clip={clip} open onClose={vi.fn()} />)

    await userEvent.click(screen.getByRole("checkbox", { name: /Second/ }))
    expect(screen.getByRole("button", { name: "Create mashup" })).toBeEnabled()
  })

  it("submits the mashup payload and reaches success", async () => {
    mockEligibleClips()
    submitMashup.mockResolvedValue({ status: "accepted", jobId: "j1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["mashup-1"] })

    render(<MashupModal clip={clip} open onClose={vi.fn()} />)
    await userEvent.click(screen.getByRole("checkbox", { name: /Second/ }))
    await userEvent.click(screen.getByRole("button", { name: "Create mashup" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    expect(submitMashup).toHaveBeenCalledWith(
      expect.objectContaining({ clip_ids: ["clip-1", "clip-2"], blend_mode: "layered" }),
      "tok"
    )
    const payload = submitMashup.mock.calls[0][0]
    expect(payload.clip_ids[0]).toBe("clip-1")
  })
})
