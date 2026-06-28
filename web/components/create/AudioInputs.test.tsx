import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { useState } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  AudioInputs,
  EMPTY_AUDIO_INPUTS,
  type AudioInputsValue,
} from "@/components/create/AudioInputs"

vi.mock("@/hooks/use-clips", () => ({ useClips: () => ({ data: null, loading: false }) }))
vi.mock("@/hooks/use-workspaces", () => ({
  useWorkspaces: () => ({ workspaces: [], defaultWorkspace: null }),
}))

beforeEach(() => {
  URL.createObjectURL = vi.fn(() => "blob:mock")
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => vi.clearAllMocks())

// Stateful harness mirroring how the forms own the selections.
function Harness() {
  const [value, setValue] = useState<AudioInputsValue>(EMPTY_AUDIO_INPUTS)
  return (
    <AudioInputs
      value={value}
      onChange={(patch) => setValue((v) => ({ ...v, ...patch }))}
    />
  )
}

describe("AudioInputs", () => {
  it("renders the three trigger buttons", () => {
    render(<Harness />)
    expect(screen.getByRole("button", { name: /audio/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /voice/i })).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /inspiration/i })
    ).toBeInTheDocument()
  })

  it("shows a removable chip after selecting a voice", async () => {
    const user = userEvent.setup()
    render(<Harness />)

    await user.click(screen.getByRole("button", { name: /voice/i }))
    await user.click(screen.getByRole("button", { name: /aria/i }))

    // Chip appears with the voice name.
    const chips = screen.getByLabelText("Attached inputs")
    expect(chips).toHaveTextContent("Aria")

    // Removing it clears the chip.
    await user.click(screen.getByRole("button", { name: /remove aria/i }))
    expect(screen.queryByLabelText("Attached inputs")).not.toBeInTheDocument()
  })
})
