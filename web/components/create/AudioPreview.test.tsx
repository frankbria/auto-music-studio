import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { AudioPreview } from "@/components/create/AudioPreview"

const originalCreateObjectURL = URL.createObjectURL
const originalRevokeObjectURL = URL.revokeObjectURL

beforeEach(() => {
  // jsdom doesn't implement object URLs.
  URL.createObjectURL = vi.fn(() => "blob:mock")
  URL.revokeObjectURL = vi.fn()
})

afterEach(() => {
  // Restore the globals so the mock doesn't leak into later suites.
  URL.createObjectURL = originalCreateObjectURL
  URL.revokeObjectURL = originalRevokeObjectURL
  vi.clearAllMocks()
})

describe("AudioPreview", () => {
  it("renders an audio element with a string source", () => {
    render(<AudioPreview source="/audio/clip.mp3" label="Clip" />)
    expect(screen.getByLabelText("Preview Clip")).toHaveAttribute(
      "src",
      "/audio/clip.mp3"
    )
  })

  it("creates an object URL for a Blob source", () => {
    const blob = new Blob(["x"], { type: "audio/webm" })
    render(<AudioPreview source={blob} />)
    expect(URL.createObjectURL).toHaveBeenCalledWith(blob)
  })

  it("calls onClear when Clear is clicked", async () => {
    const onClear = vi.fn()
    const user = userEvent.setup()
    render(<AudioPreview source="/a.mp3" onClear={onClear} />)
    await user.click(screen.getByRole("button", { name: /clear/i }))
    expect(onClear).toHaveBeenCalledOnce()
  })
})
