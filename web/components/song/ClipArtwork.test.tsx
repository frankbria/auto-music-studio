import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { ClipArtwork } from "@/components/song/ClipArtwork"

const glyph = <span data-testid="glyph" />

describe("ClipArtwork", () => {
  it("shows the clip's cover art from the same-origin artwork route", () => {
    const { container } = render(<ClipArtwork clipId="c 1" fallback={glyph} />)
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/api/clips/c%201/artwork")
    expect(screen.queryByTestId("glyph")).toBeNull()
  })

  it("falls back to the glyph when the clip has no art, never a broken image", () => {
    const { container } = render(<ClipArtwork clipId="c1" fallback={glyph} />)
    fireEvent.error(container.querySelector("img")!)
    expect(container.querySelector("img")).toBeNull()
    expect(screen.getByTestId("glyph")).toBeTruthy()
  })

  it("tries again for a different clip after a failure", () => {
    const { container, rerender } = render(<ClipArtwork clipId="c1" fallback={glyph} />)
    fireEvent.error(container.querySelector("img")!)
    rerender(<ClipArtwork clipId="c2" fallback={glyph} />)
    expect(container.querySelector("img")?.getAttribute("src")).toBe("/api/clips/c2/artwork")
  })
})
