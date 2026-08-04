import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AddVoiceModal } from "@/components/create/modals/AddVoiceModal"
import type { VoiceModelSummary } from "@/lib/voice-models"

const state = vi.hoisted(() => ({ current: null as unknown }))

vi.mock("@/hooks/use-voice-models", () => ({
  useVoiceModels: () => ({ state: state.current }),
}))

vi.mock("@/hooks/use-auth", () => ({
  useAuth: () => ({ accessToken: "token-1" }),
}))

const fetchVoicePreview = vi.hoisted(() => vi.fn())
vi.mock("@/lib/voice-models", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/voice-models")>()),
  fetchVoicePreview,
}))

function voice(over: Partial<VoiceModelSummary> = {}): VoiceModelSummary {
  return {
    id: "v1",
    name: "My Voice",
    description: "Warm and breathy",
    status: "ready",
    reference_count: 3,
    job_id: null,
    error: null,
    created_at: "2026-01-01T00:00:00Z",
    ...over,
  }
}

const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock")
  URL.revokeObjectURL = vi.fn()
  state.current = { phase: "ready", models: [voice()] }
  fetchVoicePreview.mockResolvedValue(new Blob(["audio"]))
})

afterEach(() => {
  URL.createObjectURL = originalCreateObjectURL
  URL.revokeObjectURL = originalRevokeObjectURL
  vi.clearAllMocks()
})

describe("AddVoiceModal", () => {
  it("lists the musician's trained voices", () => {
    state.current = {
      phase: "ready",
      models: [voice(), voice({ id: "v2", name: "Second Voice" })],
    }
    render(<AddVoiceModal open onOpenChange={() => {}} onSelect={() => {}} />)

    expect(screen.getByText("My Voice")).toBeInTheDocument()
    expect(screen.getByText("Second Voice")).toBeInTheDocument()
  })

  it("hides voices that are not ready to generate with", () => {
    // The backend refuses them, so offering one would only be a dead end.
    state.current = {
      phase: "ready",
      models: [
        voice({ id: "v2", name: "Still Training", status: "training" }),
        voice({ id: "v3", name: "Broken", status: "failed" }),
      ],
    }
    render(<AddVoiceModal open onOpenChange={() => {}} onSelect={() => {}} />)

    expect(screen.queryByText("Still Training")).not.toBeInTheDocument()
    expect(screen.queryByText("Broken")).not.toBeInTheDocument()
    expect(screen.getByText(/no voices are ready yet/i)).toBeInTheDocument()
  })

  it("selects a voice and closes", async () => {
    const onSelect = vi.fn()
    const onOpenChange = vi.fn()
    const user = userEvent.setup()
    render(
      <AddVoiceModal open onOpenChange={onOpenChange} onSelect={onSelect} />
    )

    await user.click(screen.getByRole("button", { name: /my voice/i }))

    expect(onSelect).toHaveBeenCalledWith({ id: "v1", name: "My Voice" })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })

  it("plays a reference recording on demand", async () => {
    const user = userEvent.setup()
    render(<AddVoiceModal open onOpenChange={() => {}} onSelect={() => {}} />)

    await user.click(screen.getByRole("button", { name: "Preview" }))

    expect(fetchVoicePreview).toHaveBeenCalledWith("v1", "token-1")
    expect(await screen.findByLabelText("Preview My Voice")).toBeInTheDocument()
  })

  it("says so rather than failing when a voice has no preview", async () => {
    fetchVoicePreview.mockRejectedValue(new Error("404"))
    const user = userEvent.setup()
    render(<AddVoiceModal open onOpenChange={() => {}} onSelect={() => {}} />)

    await user.click(screen.getByRole("button", { name: "Preview" }))

    expect(await screen.findByText(/no preview available/i)).toBeInTheDocument()
  })

  it("asks a signed-out visitor to sign in", () => {
    state.current = { phase: "signed-out" }
    render(<AddVoiceModal open onOpenChange={() => {}} onSelect={() => {}} />)

    expect(
      screen.getByText(/sign in to use your custom voices/i)
    ).toBeInTheDocument()
  })
})
