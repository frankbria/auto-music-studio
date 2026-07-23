import { render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, describe, expect, it, vi } from "vitest"

import { PreviewPlayer } from "@/components/mastering/preview-player"

afterEach(() => vi.clearAllMocks())

describe("PreviewPlayer", () => {
  it("plays the mastered source by default through the cookie-authed stream proxy", () => {
    render(<PreviewPlayer originalClipId="c1" masteredClipId="m1" />)
    const audio = screen.getByTestId("preview-audio")
    expect(audio.getAttribute("src")).toBe("/api/clips/m1/stream")
    expect(screen.getByTestId("ab-mode")).toHaveTextContent("Mastered")
  })

  it("A/B toggle swaps the source to the original and back", async () => {
    const user = userEvent.setup()
    render(<PreviewPlayer originalClipId="c1" masteredClipId="m1" />)
    const audio = screen.getByTestId("preview-audio")

    await user.click(screen.getByRole("button", { name: /compare with original/i }))
    expect(audio.getAttribute("src")).toBe("/api/clips/c1/stream")
    expect(screen.getByTestId("ab-mode")).toHaveTextContent("Original")

    await user.click(screen.getByRole("button", { name: /compare with mastered/i }))
    expect(audio.getAttribute("src")).toBe("/api/clips/m1/stream")
    expect(screen.getByTestId("ab-mode")).toHaveTextContent("Mastered")
  })

  it("exposes play/pause and seek controls", () => {
    render(<PreviewPlayer originalClipId="c1" masteredClipId="m1" />)
    expect(screen.getByRole("button", { name: /play/i })).toBeInTheDocument()
    expect(screen.getByRole("slider", { name: /seek/i })).toBeInTheDocument()
  })
})
