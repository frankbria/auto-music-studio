import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { VoiceLibrary } from "@/components/voices/VoiceLibrary"
import type { VoiceModelSummary } from "@/lib/voice-models"

vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ accessToken: "tok-1" }) }))

vi.mock("@/lib/voice-models", async () => {
  const actual = await vi.importActual<typeof import("@/lib/voice-models")>("@/lib/voice-models")
  return {
    ...actual,
    fetchVoiceModels: vi.fn(),
    updateVoiceModel: vi.fn(),
    deleteVoiceModel: vi.fn(),
    fetchTrainingStatus: vi.fn(),
  }
})

import {
  deleteVoiceModel,
  fetchTrainingStatus,
  fetchVoiceModels,
  updateVoiceModel,
  VoiceModelError,
} from "@/lib/voice-models"

const mockList = vi.mocked(fetchVoiceModels)
const mockUpdate = vi.mocked(updateVoiceModel)
const mockDelete = vi.mocked(deleteVoiceModel)
const mockStatus = vi.mocked(fetchTrainingStatus)

function model(overrides: Partial<VoiceModelSummary> = {}): VoiceModelSummary {
  return {
    id: "vm-1",
    name: "My voice",
    description: "warm baritone",
    status: "ready",
    reference_count: 3,
    job_id: "job-1",
    error: null,
    created_at: "2026-01-15T00:00:00Z",
    ...overrides,
  }
}

beforeEach(() => {
  mockList.mockReset()
  mockUpdate.mockReset()
  mockDelete.mockReset()
  mockStatus.mockReset()
})

describe("VoiceLibrary", () => {
  it("AC: lists every trained voice with the fields the story names", async () => {
    mockList.mockResolvedValue([
      model(),
      model({ id: "vm-2", name: "Second", description: "bright tenor", reference_count: 1 }),
    ])

    render(<VoiceLibrary />)

    await waitFor(() => expect(screen.getAllByTestId("voice-card")).toHaveLength(2))
    expect(screen.getByText("My voice")).toBeInTheDocument()
    expect(screen.getByText("warm baritone")).toBeInTheDocument()
    expect(screen.getByText(/3 references/)).toBeInTheDocument()
    // Singular, because "1 references" is the kind of thing nobody fixes later.
    expect(screen.getByText(/1 reference(?!s)/)).toBeInTheDocument()
    expect(screen.getAllByText("Ready")).toHaveLength(2)
  })

  it("AC: renaming updates the card", async () => {
    mockList.mockResolvedValueOnce([model()]).mockResolvedValue([model({ name: "Renamed" })])
    mockUpdate.mockResolvedValue(model({ name: "Renamed" }))

    render(<VoiceLibrary />)
    await screen.findByText("My voice")

    await userEvent.click(screen.getByRole("button", { name: "Rename" }))
    const field = screen.getByLabelText("Voice name")
    await userEvent.clear(field)
    await userEvent.type(field, "Renamed")
    await userEvent.click(screen.getByRole("button", { name: "Save" }))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledWith("vm-1", "tok-1", { name: "Renamed" }))
    // Re-read from the server rather than patched locally, so the card cannot drift.
    await waitFor(() => expect(screen.getByText("Renamed")).toBeInTheDocument())
  })

  it("AC: deleting removes it from the library", async () => {
    mockList.mockResolvedValueOnce([model()]).mockResolvedValue([])
    mockDelete.mockResolvedValue()

    render(<VoiceLibrary />)
    await screen.findByText("My voice")

    await userEvent.click(screen.getByRole("button", { name: "Delete" }))

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith("vm-1", "tok-1"))
    await waitFor(() => expect(screen.queryByTestId("voice-card")).not.toBeInTheDocument())
  })

  it("says why a delete was refused rather than failing silently", async () => {
    mockList.mockResolvedValue([model({ status: "training" })])
    mockDelete.mockRejectedValue(
      new VoiceModelError("This voice is still training. Wait for it to finish before deleting it.", 409)
    )
    mockStatus.mockResolvedValue({
      job_id: "job-1",
      voice_model_id: "vm-1",
      status: "training",
      phase: "training",
      progress: 40,
      eta_seconds: 20,
      step: 4,
      epoch: 1,
      loss: 0.5,
      error: null,
    })

    render(<VoiceLibrary />)
    await screen.findByText("My voice")

    await userEvent.click(screen.getByRole("button", { name: "Delete" }))

    expect(await screen.findByText(/still training/)).toBeInTheDocument()
    // And the card is still there.
    expect(screen.getByTestId("voice-card")).toBeInTheDocument()
  })

  it("shows live progress for a model still training", async () => {
    mockList.mockResolvedValue([model({ status: "training" })])
    mockStatus.mockResolvedValue({
      job_id: "job-1",
      voice_model_id: "vm-1",
      status: "training",
      phase: "training",
      progress: 42,
      eta_seconds: 30,
      step: 4,
      epoch: 1,
      loss: 0.5,
      error: null,
    })

    render(<VoiceLibrary />)

    expect(await screen.findByText(/Training — 42%/)).toBeInTheDocument()
  })

  it("a null progress shows the phase alone, never 0%", async () => {
    // 0% reads as "stuck"; the server reports null when it cannot know.
    mockList.mockResolvedValue([model({ status: "training" })])
    mockStatus.mockResolvedValue({
      job_id: "job-1",
      voice_model_id: "vm-1",
      status: "training",
      phase: "training",
      progress: null,
      eta_seconds: null,
      step: null,
      epoch: null,
      loss: null,
      error: null,
    })

    render(<VoiceLibrary />)

    expect(await screen.findByText("Training")).toBeInTheDocument()
    expect(screen.queryByText(/0%/)).not.toBeInTheDocument()
  })

  it("shows why a training run failed", async () => {
    mockList.mockResolvedValue([model({ status: "failed", error: "CUDA out of memory", job_id: null })])

    render(<VoiceLibrary />)

    expect(await screen.findByText("CUDA out of memory")).toBeInTheDocument()
  })

  it("invites a first voice when the library is empty", async () => {
    mockList.mockResolvedValue([])

    render(<VoiceLibrary />)

    expect(await screen.findByText(/No voice models yet/)).toBeInTheDocument()
  })
})
