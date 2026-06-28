import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AddVoiceModal } from "@/components/create/modals/AddVoiceModal"
import { MOCK_VOICES } from "@/lib/audio-inputs"

const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock")
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  URL.createObjectURL = originalCreateObjectURL
  URL.revokeObjectURL = originalRevokeObjectURL
  vi.clearAllMocks()
})

describe("AddVoiceModal", () => {
  it("lists the available voice models", () => {
    render(<AddVoiceModal open onOpenChange={() => {}} onSelect={() => {}} />)
    for (const voice of MOCK_VOICES) {
      expect(screen.getByText(voice.name)).toBeInTheDocument()
    }
  })

  it("selects a voice and closes", async () => {
    const onSelect = vi.fn()
    const onOpenChange = vi.fn()
    const user = userEvent.setup()
    render(
      <AddVoiceModal open onOpenChange={onOpenChange} onSelect={onSelect} />
    )

    await user.click(screen.getByRole("button", { name: /aria/i }))
    expect(onSelect).toHaveBeenCalledWith({ id: "voice-aria", name: "Aria" })
    expect(onOpenChange).toHaveBeenCalledWith(false)
  })
})
