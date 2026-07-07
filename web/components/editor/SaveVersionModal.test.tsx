import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { SaveVersionModal } from "@/components/editor/SaveVersionModal"
import type { ClipAudio } from "@/lib/audio-peaks"
import type { EditOperation } from "@/lib/waveform-edit"

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "tok", isLoading: false, isAuthenticated: true }),
}))

const saveClipVersion = vi.fn()
vi.mock("@/lib/editing", () => ({
  saveClipVersion: (...args: unknown[]) => saveClipVersion(...args),
}))

const fetchJobStatus = vi.fn()
vi.mock("@/lib/job-status", () => ({
  fetchJobStatus: (...args: unknown[]) => fetchJobStatus(...args),
}))

afterEach(() => vi.clearAllMocks())

const audio: ClipAudio = { mono: new Float32Array(80), sampleRate: 8000, duration: 0.01 }
const ops: EditOperation[] = [{ kind: "delete", startSec: 1, endSec: 2 }]

function renderModal(operations = ops) {
  return render(
    <SaveVersionModal
      clipId="clip-1"
      audio={audio}
      operations={operations}
      open
      onClose={vi.fn()}
    />
  )
}

describe("SaveVersionModal", () => {
  it("shows an optional title field and the number of edits to save", () => {
    renderModal()
    expect(screen.getByRole("dialog")).toHaveTextContent("Save as new version")
    expect(screen.getByLabelText(/Title/)).toBeInTheDocument()
    expect(screen.getByText("1 edit will be saved.")).toBeInTheDocument()
  })

  it("disables save when there are no edits to persist", () => {
    renderModal([])
    expect(screen.getByRole("button", { name: "Save version" })).toBeDisabled()
  })

  it("uploads the encoded audio + operations and reaches success", async () => {
    saveClipVersion.mockResolvedValue({ status: "accepted", jobId: "v1", estimatedSeconds: 0 })
    fetchJobStatus.mockResolvedValue({ kind: "completed", clipIds: ["version-1"] })

    renderModal()
    await userEvent.type(screen.getByLabelText(/Title/), "Radio edit")
    await userEvent.click(screen.getByRole("button", { name: "Save version" }))

    await waitFor(() =>
      expect(screen.getByText("Your new clip is ready.")).toBeInTheDocument()
    )
    const [clipId, wav, meta, token] = saveClipVersion.mock.calls[0]
    expect(clipId).toBe("clip-1")
    expect(wav).toBeInstanceOf(Blob) // encoded WAV, not raw samples
    expect(meta).toEqual({ title: "Radio edit", operations: ops })
    expect(token).toBe("tok")
  })

  it("surfaces a backend error without crashing", async () => {
    saveClipVersion.mockResolvedValue({ status: "error", detail: "Not Found" })
    renderModal()
    await userEvent.click(screen.getByRole("button", { name: "Save version" }))
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Not Found"))
  })
})
