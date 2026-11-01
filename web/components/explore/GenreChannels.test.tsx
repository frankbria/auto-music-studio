import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { GenreChannels } from "@/components/explore/GenreChannels"

describe("GenreChannels", () => {
  it("encodes a slug with a symbol, so R&B searches the style r&b (#657)", () => {
    render(<GenreChannels />)
    expect(screen.getByRole("link", { name: /R&B/ })).toHaveAttribute(
      "href",
      "/search?style=r%26b"
    )
  })
})
