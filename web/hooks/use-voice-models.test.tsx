import { renderHook, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useVoiceModels } from "@/hooks/use-voice-models"
import type { VoiceModelSummary } from "@/lib/voice-models"

let currentToken: string | null = "tok-1"
vi.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ accessToken: currentToken }) }))

vi.mock("@/lib/voice-models", async () => {
  const actual = await vi.importActual<typeof import("@/lib/voice-models")>("@/lib/voice-models")
  return { ...actual, fetchVoiceModels: vi.fn(), updateVoiceModel: vi.fn(), deleteVoiceModel: vi.fn() }
})

import { fetchVoiceModels } from "@/lib/voice-models"

const mockList = vi.mocked(fetchVoiceModels)

const model: VoiceModelSummary = {
  id: "vm-1",
  name: "My voice",
  description: null,
  status: "ready",
  reference_count: 3,
  job_id: null,
  error: null,
  created_at: "2026-01-15T00:00:00Z",
}

beforeEach(() => {
  mockList.mockReset()
  currentToken = "tok-1"
})

describe("useVoiceModels", () => {
  it("loads the library", async () => {
    mockList.mockResolvedValue([model])

    const { result } = renderHook(() => useVoiceModels())

    await waitFor(() => expect(result.current.state.phase).toBe("ready"))
    expect(result.current.state).toMatchObject({ models: [model] })
  })

  it("with no token it reports signed-out instead of spinning forever", async () => {
    currentToken = null

    const { result } = renderHook(() => useVoiceModels())

    await waitFor(() => expect(result.current.state.phase).toBe("signed-out"))
    expect(mockList).not.toHaveBeenCalled()
  })

  it("clearing the token drops the loaded models rather than leaving them on screen", async () => {
    // Private metadata must not survive a logout or a failed refresh.
    mockList.mockResolvedValue([model])

    const { result, rerender } = renderHook(() => useVoiceModels())
    await waitFor(() => expect(result.current.state.phase).toBe("ready"))

    currentToken = null
    rerender()

    await waitFor(() => expect(result.current.state.phase).toBe("signed-out"))
    expect(result.current.state).not.toHaveProperty("models")
  })
})
